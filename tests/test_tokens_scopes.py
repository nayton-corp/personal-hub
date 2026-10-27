"""L0-05 : chaque portée autorisée et refusée ; jeton montré une fois, stocké en empreinte."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from hub.core import tokens
from hub.core.auth import Principal
from hub.core.context import HubContext
from tests.conftest import bearer


def test_expand_shortcuts() -> None:
    assert set(tokens.expand_scopes(["brain"])) == {"finance:read", "finance:propose"}
    assert tokens.expand_scopes(["aggregates"]) == ["*:aggregates"]
    assert tokens.expand_scopes(["collector"]) == ["core:collector"]
    assert tokens.expand_scopes(["demo:read", "demo:read"]) == ["demo:read"]


@pytest.mark.parametrize("bad", [["app"], ["*:read"], ["finance:write"], ["root"], []])
def test_invalid_scopes(bad: list[str]) -> None:
    with pytest.raises(tokens.ScopeError):
        tokens.expand_scopes(bad)


def test_principal_wildcard() -> None:
    p = Principal("token:x", frozenset({"*:aggregates"}))
    assert p.allows("finance:aggregates")
    assert not p.allows("finance:read")
    assert Principal("passkey:y", frozenset(), is_app=True).allows("anything:read")


def test_token_is_stored_as_hash_and_revocable(hub: HubContext) -> None:
    with hub.core.engine.begin() as conn:
        info, secret = tokens.create(conn, "brain-mac", ["brain"], "system:test")
    assert secret.startswith("hub_")
    assert len(secret) > 40
    with hub.core.engine.connect() as conn:
        stored = conn.execute(text("SELECT secret_hash FROM tokens")).scalar_one()
        dump = "".join(str(r) for r in conn.execute(text("SELECT * FROM tokens")))
    assert stored == tokens.hash_secret(secret)
    assert secret not in dump
    with hub.core.engine.begin() as conn:
        assert tokens.verify(conn, secret) is not None
        assert tokens.verify(conn, "hub_wrong") is None
        assert tokens.verify(conn, "nope") is None
        assert tokens.revoke(conn, info.id, "system:test")
        assert not tokens.revoke(conn, info.id, "system:test")
        assert tokens.verify(conn, secret) is None
        listed = tokens.list_all(conn)
    assert listed[0].revoked_at is not None
    assert listed[0].last_used_at is not None
    with hub.core.engine.connect() as conn:
        actions = [r[0] for r in conn.execute(text("SELECT action FROM audit ORDER BY seq"))]
    assert actions == ["token.create", "token.revoke", "token.revoke"]


def test_health_needs_no_auth(client: TestClient) -> None:
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["core"]["ok"] is True
    assert body["domains"]["demo"] == {"db": "ok", "schema_version": 1, "ok": True}
    assert r.headers["cache-control"] == "no-store"


# (route, portées autorisées, portées refusées)
MATRIX = [
    (
        "/api/demo/items",
        ["demo:read"],
        ["demo:aggregates", "demo:propose", "*:aggregates", "core:collector", "other:read"],
    ),
    (
        "/api/demo/summary",
        ["demo:read", "demo:aggregates", "*:aggregates"],
        ["demo:propose", "core:collector"],
    ),
    ("/api/proposals", ["demo:read", "demo:propose"], ["demo:aggregates", "core:collector"]),
    ("/api/search?q=abc", ["demo:read"], ["demo:propose", "demo:aggregates", "core:collector"]),
    ("/api/auth/passkeys", [], ["demo:read", "demo:propose", "*:aggregates", "core:collector"]),
]


@pytest.mark.parametrize(("route", "allowed", "denied"), MATRIX)
def test_scope_matrix(
    client: TestClient,
    make_token,
    route: str,
    allowed: list[str],  # type: ignore[no-untyped-def]
    denied: list[str],
) -> None:
    for scope in allowed:
        r = client.get(route, headers=bearer(make_token(scope)))
        assert r.status_code == 200, (route, scope, r.text)
    for scope in denied:
        r = client.get(route, headers=bearer(make_token(scope)))
        assert r.status_code == 403, (route, scope)
        assert r.headers["content-type"] == "application/problem+json"
        assert r.json()["type"] == "auth.scope"


def test_missing_and_invalid_auth(client: TestClient) -> None:
    r = client.get("/api/demo/items")
    assert (r.status_code, r.json()["type"]) == (401, "auth.missing")
    r = client.get("/api/demo/items", headers=bearer("hub_forged"))
    assert (r.status_code, r.json()["type"]) == (401, "auth.invalid")
    r = client.get("/api/demo/items", headers={"Authorization": "Basic abc"})
    assert r.status_code == 401
    client.cookies.set("hub_session", "forged")
    r = client.get("/api/demo/items")
    assert (r.status_code, r.json()["type"]) == (401, "auth.invalid")


def test_unknown_route_is_problem_json(client: TestClient) -> None:
    r = client.get("/api/nope")
    assert r.status_code == 404
    assert r.json()["type"] == "not_found"
