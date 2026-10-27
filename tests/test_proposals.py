"""Création idempotente des propositions, refus, expiration et réconciliation."""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from hub.core import proposals
from hub.core.auth import Principal
from hub.core.clock import iso, utcnow
from hub.core.context import HubContext
from hub.core.errors import Problem
from hub.core.maintenance import nightly
from tests.conftest import bearer
from tests.support.demo_domain import DemoDomain

APP = Principal("passkey:test", frozenset({"app"}), is_app=True)


def _post(client: TestClient, token: str, body: dict, key: str | None = None):  # type: ignore[no-untyped-def,type-arg]
    headers = bearer(token) | ({"Idempotency-Key": key} if key else {})
    return client.post("/api/proposals", json=body, headers=headers)


BODY = {"domain": "demo", "kind": "add_item", "params": {"name": "pain"}, "reason": "test"}


def test_create_returns_preview(client: TestClient, make_token) -> None:  # type: ignore[no-untyped-def]
    r = _post(client, make_token("demo:propose"), BODY)
    assert r.status_code == 201, r.text
    p = r.json()
    assert p["status"] == "pending"
    assert p["revision"] == 1
    assert p["tier"] == "human"
    assert p["preview"] == {"summary": "ajouter pain", "details": {"count_before": 0}}
    assert p["created_by"].startswith("token:")
    assert p["urn"] == f"hub:core:proposal:{p['id']}"


def test_same_key_returns_same_proposal(client: TestClient, make_token) -> None:  # type: ignore[no-untyped-def]
    token = make_token("demo:propose")
    first = _post(client, token, BODY, key="k1")
    again = _post(client, token, BODY, key="k1")
    assert (first.status_code, again.status_code) == (201, 200)
    assert first.json()["id"] == again.json()["id"]
    other = _post(client, token, BODY | {"params": {"name": "lait"}}, key="k1")
    assert (other.status_code, other.json()["type"]) == (409, "idempotency.key_mismatch")


def test_identical_pending_is_not_duplicated(
    client: TestClient, make_token, hub: HubContext
) -> None:  # type: ignore[no-untyped-def]
    token = make_token("demo:propose")
    a = _post(client, token, BODY).json()
    b = _post(client, token, BODY, key="fresh").json()
    assert a["id"] == b["id"]
    with hub.core.engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM proposals")).scalar() == 1


def test_kind_rules(client: TestClient, make_token) -> None:  # type: ignore[no-untyped-def]
    propose = make_token("demo:propose")
    r = _post(client, propose, BODY | {"kind": "add_item_human_only"})
    assert (r.status_code, r.json()["type"]) == (403, "proposal.kind_not_allowed")
    r = _post(client, propose, BODY | {"kind": "nope"})
    assert (r.status_code, r.json()["type"]) == (422, "proposal.kind_unknown")
    r = _post(client, propose, BODY | {"domain": "ghost"})
    assert (r.status_code, r.json()["type"]) == (404, "domain.unknown")
    r = _post(client, propose, BODY | {"params": {"name": ""}})
    assert (r.status_code, r.json()["type"]) == (422, "validation.params")
    assert "pain" not in r.text
    r = _post(client, make_token("demo:read"), BODY)
    assert (r.status_code, r.json()["type"]) == (403, "auth.scope")
    r = client.post("/api/proposals", json={"domain": "demo"}, headers=bearer(propose))
    assert r.status_code == 422


def test_app_may_create_human_only_kinds(hub: HubContext) -> None:
    p, created = proposals.create(hub, APP, "demo", "add_item_human_only", {"name": "x"})
    assert created
    assert p.created_by == "passkey:test"


def test_external_kind_previews_without_db(hub: HubContext, demo: DemoDomain) -> None:
    p, _ = proposals.create(hub, APP, "demo", "notify", {"name": "x"})
    assert p.preview["summary"] == "appel externe"
    assert demo.third_party.apply(None, "k").status == "ok"  # type: ignore[arg-type]
    assert demo.third_party.apply(None, "k").detail == {"calls": 1}  # type: ignore[arg-type]


def test_policy_tier_is_recorded(hub: HubContext) -> None:
    with hub.core.engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO approval_policies (domain, kind, tier) "
                "VALUES ('demo', 'add_item', 'auto')"
            )
        )
    p, _ = proposals.create(hub, APP, "demo", "add_item", {"name": "x"})
    assert p.tier == "auto"


def test_list_get_reject(client: TestClient, make_token, hub: HubContext) -> None:  # type: ignore[no-untyped-def]
    reader = make_token("demo:read")
    created = _post(client, make_token("demo:propose"), BODY).json()
    listed = client.get("/api/proposals", headers=bearer(reader)).json()["items"]
    assert [p["id"] for p in listed] == [created["id"]]
    got = client.get(f"/api/proposals/{created['id']}", headers=bearer(reader))
    assert got.status_code == 200
    assert client.get("/api/proposals/nope", headers=bearer(reader)).status_code == 404
    # le refus est réservé à l'app
    r = client.post(f"/api/proposals/{created['id']}/reject", headers=bearer(reader))
    assert r.status_code == 403
    p = proposals.reject(hub, APP, created["id"])
    assert p.status == "rejected"
    assert p.decided_at
    with pytest.raises(Problem) as exc:
        proposals.reject(hub, APP, created["id"])
    assert exc.value.type == "proposal.not_pending"
    assert (
        client.get("/api/proposals?status=rejected", headers=bearer(reader)).json()["items"][0][
            "status"
        ]
        == "rejected"
    )
    # après refus, une nouvelle proposition identique est permise
    _p, again = proposals.create(hub, APP, "demo", "add_item", {"name": "pain"})
    assert again


def test_expire_and_reconcile(hub: HubContext, demo: DemoDomain) -> None:
    old, _ = proposals.create(hub, APP, "demo", "add_item", {"name": "old"})
    done, _ = proposals.create(hub, APP, "demo", "add_item", {"name": "done"})
    stuck, _ = proposals.create(hub, APP, "demo", "add_item", {"name": "stuck"})
    recent, _ = proposals.create(hub, APP, "demo", "add_item", {"name": "recent"})
    past = iso(utcnow() - timedelta(hours=1))
    long_ago = iso(utcnow() - timedelta(minutes=10))
    with hub.core.engine.begin() as conn:
        conn.execute(
            text("UPDATE proposals SET expires_at = :p WHERE id = :id"), {"p": past, "id": old.id}
        )
        conn.execute(
            text("UPDATE proposals SET status = 'applying', claimed_at = :t WHERE id IN (:a, :b)"),
            {"t": long_ago, "a": done.id, "b": stuck.id},
        )
        conn.execute(
            text("UPDATE proposals SET status = 'applying', claimed_at = :t WHERE id = :id"),
            {"t": iso(utcnow()), "id": recent.id},
        )
    demo.mark_applied(done.id, {"seq": 7})
    result = nightly(hub)
    assert result["expired"] == 1
    assert (result["reconciled_applied"], result["reconciled_released"]) == (1, 1)
    assert demo.nightly_runs == 1
    with hub.core.engine.connect() as conn:
        status = dict(conn.execute(text("SELECT id, status FROM proposals")).fetchall())
        assert proposals.get(conn, done.id).result == {"seq": 7}
    assert status == {
        old.id: "expired",
        done.id: "applied",
        stuck.id: "pending",
        recent.id: "applying",
    }
