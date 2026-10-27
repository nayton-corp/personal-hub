"""L3-02, côté cœur : validation signée, lots, conflits, idempotence, paliers, inverses, CLI."""

from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from typer.testing import CliRunner

from hub import cli as hub_cli
from hub.core import db as core_db
from hub.core import proposals
from hub.core.auth import Principal
from hub.core.clock import iso, utcnow
from hub.core.context import HubContext
from hub.core.errors import Problem
from tests.support.demo_domain import DemoDomain
from tests.support.soft_authenticator import SoftAuthenticator
from tests.test_passkeys import ORIGIN, _code, _register

APP = Principal("passkey:test", frozenset({"app"}), is_app=True)


@pytest.fixture
def phone(client: TestClient, hub: HubContext) -> SoftAuthenticator:
    auth = SoftAuthenticator("hub.example.ts.net", ORIGIN)
    assert _register(client, auth, _code(hub)).status_code == 200
    return auth


def items(demo: DemoDomain) -> list[str]:
    with demo.engine().connect() as conn:
        return [r[0] for r in conn.execute(text("SELECT name FROM items ORDER BY seq"))]


def new(
    hub: HubContext, name: str = "pain", kind: str = "add_item", **kw: Any
) -> proposals.Proposal:
    p, _ = proposals.create(hub, APP, "demo", kind, {"name": name}, **kw)
    return p


def sign(
    client: TestClient, phone: SoftAuthenticator, ids: list[str], action: str = "accept"
) -> dict[str, Any]:
    r = client.post("/api/approvals/challenge", json={"proposal_ids": ids, "action": action})
    assert r.status_code == 200, r.text
    body = r.json()
    return {"challenge_id": body["challenge_id"], "assertion": phone.sign(body["options"])}


def test_challenge_contains_the_digest(client: TestClient, hub: HubContext, phone) -> None:  # type: ignore[no-untyped-def]
    p = new(hub)
    body = client.post("/api/approvals/challenge", json={"proposal_ids": [p.id]}).json()
    assert body["approval_digest"] == proposals.approval_digest([p])
    from webauthn.helpers import base64url_to_bytes

    challenge = base64url_to_bytes(body["options"]["challenge"])
    assert challenge[:32].hex() == body["approval_digest"]


def test_signed_batch_applies_each(
    client: TestClient, hub: HubContext, demo: DemoDomain, phone
) -> None:  # type: ignore[no-untyped-def]
    a, b = new(hub, "pain"), new(hub, "lait")
    signed = sign(client, phone, [a.id, b.id])
    r = client.post("/api/proposals/accept", json={"proposal_ids": [a.id, b.id], **signed})
    assert r.status_code == 200, r.text
    # chaque proposition s'applique seule : l'aperçu de « lait » comptait les éléments, il a
    # changé avec « pain », donc « lait » passe en révision 2 au lieu de s'appliquer
    first, second = r.json()["results"]
    assert first["status"] == "applied"
    assert (second["status"], second["problem"]["type"]) == ("pending", "conflict.state_changed")
    signed_b = sign(client, phone, [b.id])
    r = client.post("/api/proposals/accept", json={"proposal_ids": [b.id], **signed_b})
    assert r.json()["results"][0]["status"] == "applied"
    assert items(demo) == ["pain", "lait"]
    with hub.core.engine.connect() as conn:
        got = proposals.get(conn, a.id)
        assert json.loads(
            conn.execute(
                text("SELECT signature_json FROM proposals WHERE id = :i"), {"i": a.id}
            ).scalar_one()
        )["approval_digest"]
        actions = [r[0] for r in conn.execute(text("SELECT action FROM audit ORDER BY seq"))]
    assert got.status == "applied"
    assert actions.count("proposal.accept") == 2
    # rejouer la même validation : même réponse, aucun effet ; le défi ne sert qu'une fois
    again = client.post("/api/proposals/accept", json={"proposal_ids": [a.id, b.id], **signed})
    assert again.status_code == 401
    resigned = sign(client, phone, [a.id])
    r = client.post("/api/proposals/accept", json={"proposal_ids": [a.id], **resigned})
    assert r.json()["results"] == [
        {"id": a.id, "status": "applied", "result": {"seq": 1}, "problem": None}
    ]
    assert items(demo) == ["pain", "lait"]


def test_signature_on_another_revision_is_refused(
    client: TestClient, hub: HubContext, demo: DemoDomain, phone
) -> None:  # type: ignore[no-untyped-def]
    p = new(hub)
    signed = sign(client, phone, [p.id])
    # la carte change de révision après la signature
    with hub.core.engine.begin() as conn:
        conn.execute(text("UPDATE proposals SET revision = 2 WHERE id = :i"), {"i": p.id})
    r = client.post("/api/proposals/accept", json={"proposal_ids": [p.id], **signed})
    assert (r.status_code, r.json()["type"]) == (401, "approval.signature_invalid")
    assert items(demo) == []
    # une signature pour une autre carte ne vaut pas non plus
    other = new(hub, "autre")
    signed = sign(client, phone, [other.id])
    r = client.post("/api/proposals/accept", json={"proposal_ids": [p.id], **signed})
    assert r.status_code == 401
    # assertion falsifiée
    signed = sign(client, phone, [p.id])
    signed["assertion"]["response"]["signature"] = signed["assertion"]["response"]["clientDataJSON"]
    r = client.post("/api/proposals/accept", json={"proposal_ids": [p.id], **signed})
    assert r.status_code == 401


def test_accept_requires_a_passkey_session(client: TestClient, hub: HubContext, make_token) -> None:  # type: ignore[no-untyped-def]
    p = new(hub)
    from tests.conftest import bearer

    h = bearer(make_token("demo:propose", "demo:read"))
    r = client.post("/api/approvals/challenge", json={"proposal_ids": [p.id]}, headers=h)
    assert r.status_code == 403
    r = client.post(
        "/api/proposals/accept",
        json={"proposal_ids": [p.id], "challenge_id": "x", "assertion": {}},
        headers=h,
    )
    assert r.status_code == 403


def test_state_change_between_preview_and_accept(
    client: TestClient, hub: HubContext, demo: DemoDomain, phone
) -> None:  # type: ignore[no-untyped-def]
    p = new(hub, "pain")
    with demo.engine().begin() as conn:  # l'état lu par l'aperçu change
        conn.execute(text("INSERT INTO items (name) VALUES ('arrivé entre-temps')"))
    signed = sign(client, phone, [p.id])
    r = client.post("/api/proposals/accept", json={"proposal_ids": [p.id], **signed})
    (res,) = r.json()["results"]
    assert res["status"] == "pending"
    assert res["problem"]["type"] == "conflict.state_changed"
    assert res["problem"]["proposal"]["revision"] == 2
    assert res["problem"]["proposal"]["preview"]["details"] == {"count_before": 1}
    assert items(demo) == ["arrivé entre-temps"]
    # la nouvelle révision se valide normalement
    signed = sign(client, phone, [p.id])
    r = client.post("/api/proposals/accept", json={"proposal_ids": [p.id], **signed})
    assert r.json()["results"][0]["status"] == "applied"


def test_concurrent_accepts_apply_once(hub: HubContext, demo: DemoDomain) -> None:
    p = new(hub)
    barrier = threading.Barrier(4)
    outcomes: list[str] = []

    def go() -> None:
        barrier.wait()
        try:
            outcomes.append(proposals.accept_one(hub, APP, p, None).status)
        except Problem as exc:
            outcomes.append(exc.type)

    threads = [threading.Thread(target=go) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert items(demo) == ["pain"]
    assert "applied" in outcomes
    assert set(outcomes) <= {"applied", "proposal.not_pending"}


def test_commit_error_never_applies_twice(
    hub: HubContext, demo: DemoDomain, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Erreur ambiguë : l'effet est validé mais l'appel lève quand même."""
    p = new(hub)
    real = core_db.begin_immediate

    @contextmanager
    def flaky(engine):  # type: ignore[no-untyped-def]
        with real(engine) as conn:
            yield conn
        raise RuntimeError("disk I/O error au COMMIT")

    monkeypatch.setattr(proposals, "begin_immediate", flaky)
    with pytest.raises(RuntimeError):
        proposals.accept_one(hub, APP, p, None)
    monkeypatch.setattr(proposals, "begin_immediate", real)
    with hub.core.engine.connect() as conn:
        assert proposals.get(conn, p.id).status == "applied"  # réconcilié aussitôt
    assert proposals.accept_one(hub, APP, p, None).status == "applied"
    assert items(demo) == ["pain"]


def test_ambiguous_commit_seen_by_a_later_accept(hub: HubContext, demo: DemoDomain) -> None:
    """La base du domaine a l'effet mais core.db est resté en pending (restauration)."""
    p = new(hub)
    demo.mark_applied(p.id, {"seq": 99})
    assert proposals.accept_one(hub, APP, p, None).result == {"seq": 99}
    assert items(demo) == []


def test_busy_releases_the_claim(hub: HubContext, monkeypatch: pytest.MonkeyPatch) -> None:
    p = new(hub)

    @contextmanager
    def busy(engine):  # type: ignore[no-untyped-def]
        raise core_db.DatabaseBusy
        yield

    monkeypatch.setattr(proposals, "begin_immediate", busy)
    with pytest.raises(Problem) as exc:
        proposals.accept_one(hub, APP, p, None)
    assert exc.value.type == "busy.retry"
    assert exc.value.headers == {"Retry-After": "2"}
    with hub.core.engine.connect() as conn:
        assert proposals.get(conn, p.id).status == "pending"


def test_expired_and_final(hub: HubContext) -> None:
    p = new(hub)
    with hub.core.engine.begin() as conn:
        conn.execute(
            text("UPDATE proposals SET expires_at = :t WHERE id = :i"),
            {"t": iso(utcnow()), "i": p.id},
        )
        p = proposals.get(conn, p.id)
    with pytest.raises(Problem) as exc:
        proposals.accept_one(hub, APP, p, None)
    assert exc.value.type == "proposal.expired"
    q = new(hub, "x")
    proposals.reject(hub, APP, q.id)
    (out,) = proposals.accept(hub, APP, [q], None)
    assert (out.status, out.problem and out.problem["type"]) == ("rejected", "proposal.not_pending")
    with pytest.raises(Problem):
        proposals.load_many(hub, [])


def test_external_effect(hub: HubContext, demo: DemoDomain) -> None:
    p = new(hub, kind="notify")
    out = proposals.accept_one(hub, APP, p, None)
    assert (out.status, out.result) == ("applied", {"calls": 1})
    assert list(demo.third_party.calls) == [f"{p.id}:1"]
    # inconnu, puis réconcilié auprès du tiers
    q = new(hub, "y", kind="notify")
    with hub.core.engine.begin() as conn:
        conn.execute(text("UPDATE proposals SET status = 'unknown' WHERE id = :i"), {"i": q.id})
    assert proposals.reconcile(hub).marked_applied == 1


def test_policy_tiers_and_digest(
    client: TestClient, hub: HubContext, demo: DemoDomain, make_token, phone
) -> None:  # type: ignore[no-untyped-def]
    with hub.core.engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO approval_policies (domain, kind, tier) VALUES "
                "('demo', 'add_item', 'auto_digest')"
            )
        )
    from tests.conftest import bearer

    h = bearer(make_token("demo:propose"))
    body = {"domain": "demo", "kind": "add_item", "params": {"name": "auto"}}
    # un modèle sans déclaration reste au palier human
    r = client.post("/api/proposals", json=body, headers=h).json()
    assert (r["tier"], r["status"]) == ("human", "pending")
    r = client.post(
        "/api/proposals",
        json=body | {"params": {"name": "sûr"}, "external_text": False},
        headers=h,
    ).json()
    assert (r["tier"], r["status"]) == ("auto_digest", "applied")
    assert items(demo) == ["sûr"]
    day = client.get("/api/digest").json()
    assert [i["id"] for i in day["items"]] == [r["id"]]
    assert day["items"][0]["reversible"] is False
    assert client.get("/api/digest?day=2000-01-01").json()["items"] == []
    assert client.get("/api/digest", headers=h).status_code == 403


def test_cli_proposals(hub: HubContext, demo: DemoDomain, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hub_cli, "_ready", lambda: hub)
    runner = CliRunner()
    p = new(hub, "cli")
    out = runner.invoke(hub_cli.app, ["proposals", "list"]).stdout
    assert p.id in out
    assert "ajouter cli" in out
    assert json.loads(runner.invoke(hub_cli.app, ["proposals", "show", p.id]).stdout)["id"] == p.id
    assert runner.invoke(hub_cli.app, ["proposals", "show", "nope"]).exit_code == 1
    r = runner.invoke(hub_cli.app, ["proposals", "accept", p.id])
    assert r.exit_code == 0, r.stdout
    assert json.loads(r.stdout)["status"] == "applied"
    assert items(demo) == ["cli"]
    assert runner.invoke(hub_cli.app, ["proposals", "accept", p.id]).exit_code == 0
    q = new(hub, "refus")
    assert (
        json.loads(runner.invoke(hub_cli.app, ["proposals", "reject", q.id]).stdout)["status"]
        == "rejected"
    )
    assert runner.invoke(hub_cli.app, ["proposals", "reject", q.id]).exit_code == 1
    assert runner.invoke(hub_cli.app, ["proposals", "accept", q.id]).exit_code == 1
    r = runner.invoke(
        hub_cli.app,
        ["proposals", "create", "demo", "add_item", "--params", '{"name": "direct"}', "--accept"],
    )
    assert r.exit_code == 0, r.stdout
    assert items(demo) == ["cli", "direct"]
    assert (
        runner.invoke(
            hub_cli.app, ["proposals", "create", "demo", "add_item", "--params", "{"]
        ).exit_code
        == 1
    )
    assert runner.invoke(hub_cli.app, ["proposals", "create", "demo", "nope"]).exit_code == 1
    assert "applied" in runner.invoke(hub_cli.app, ["proposals", "list", "--status", "all"]).stdout
    with hub.core.engine.connect() as conn:
        actor = conn.execute(
            text("SELECT actor FROM audit WHERE action = 'proposal.accept' LIMIT 1")
        ).scalar_one()
    assert actor == "system:cli"
