"""L0-06 : inscription par code d'amorçage, seconde passkey, connexion, session de 12 h."""

from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from hub.core import sessions
from hub.core.context import HubContext
from hub.kernel.clock import iso, utcnow
from tests.support.soft_authenticator import SoftAuthenticator

ORIGIN = "https://hub.example.ts.net"


def _code(hub: HubContext) -> str:
    with hub.core.engine.begin() as conn:
        return sessions.create_bootstrap_code(conn, 10, "system:test")


def _confirm(client: TestClient, holder: SoftAuthenticator) -> dict[str, Any]:
    """Une passkey en place signe le geste (Face ID)."""
    begin = client.post("/api/auth/passkey/confirm/begin").json()
    return {"challenge_id": begin["challenge_id"], "credential": holder.sign(begin["options"])}


def _register(  # type: ignore[no-untyped-def]
    client: TestClient,
    auth: SoftAuthenticator,
    code: str | None,
    name: str = "iPhone",
    holder: SoftAuthenticator | None = None,
):
    confirm = _confirm(client, holder) if holder is not None else None
    begin = client.post(
        "/api/auth/passkey/register/begin", json={"bootstrap_code": code, "confirm": confirm}
    )
    assert begin.status_code == 200, begin.text
    body = begin.json()
    assert body["options"]["rp"]["id"] == "hub.example.ts.net"
    assert body["options"]["authenticatorSelection"]["userVerification"] == "required"
    return client.post(
        "/api/auth/passkey/register/finish",
        json={
            "challenge_id": body["challenge_id"],
            "credential": auth.register(body["options"]),
            "device_name": name,
            "bootstrap_code": code,
        },
    )


def _login(client: TestClient, auth: SoftAuthenticator, **kw):  # type: ignore[no-untyped-def]
    begin = client.post("/api/auth/passkey/login/begin").json()
    return client.post(
        "/api/auth/passkey/login/finish",
        json={
            "challenge_id": begin["challenge_id"],
            "credential": auth.sign(begin["options"], **kw),
        },
    )


@pytest.fixture
def phone() -> SoftAuthenticator:
    return SoftAuthenticator("hub.example.ts.net", ORIGIN)


def test_bootstrap_register_then_login(
    client: TestClient, hub: HubContext, phone: SoftAuthenticator
) -> None:
    assert client.get("/api/auth/session").json() == {
        "authenticated": False,
        "actor": None,
        "expires_at": None,
        "passkeys": 0,
        "needs_bootstrap": True,
    }
    r = _register(client, phone, _code(hub))
    assert r.status_code == 200, r.text
    cookie = r.headers["set-cookie"]
    expected = ["httponly", "secure", "samesite=strict", "path=/api", f"max-age={12 * 3600}"]
    assert all(attr in cookie.lower() for attr in expected)
    session = client.get("/api/auth/session").json()
    assert session["authenticated"]
    assert session["actor"] == f"passkey:{phone.id}"
    # la session vaut portée app
    assert client.get("/api/auth/passkeys").json()["items"][0]["device_name"] == "iPhone"
    assert client.get("/api/demo/items").status_code == 200

    client.post("/api/auth/logout")
    client.cookies.clear()
    assert client.get("/api/auth/passkeys").status_code == 401
    r = _login(client, phone)
    assert r.status_code == 200, r.text
    assert client.get("/api/auth/passkeys").status_code == 200
    with hub.core.engine.connect() as conn:
        assert conn.execute(text("SELECT sign_count FROM passkeys")).scalar() == 1


def test_bootstrap_code_is_single_use(
    client: TestClient, hub: HubContext, phone: SoftAuthenticator
) -> None:
    code = _code(hub)
    assert _register(client, phone, code).status_code == 200
    client.cookies.clear()
    r = client.post("/api/auth/passkey/register/begin", json={"bootstrap_code": code})
    assert (r.status_code, r.json()["type"]) == (401, "auth.bootstrap_invalid")
    r = client.post("/api/auth/passkey/register/begin", json={})
    assert r.status_code == 401


def test_expired_bootstrap_code(client: TestClient, hub: HubContext) -> None:
    code = _code(hub)
    with hub.core.engine.begin() as conn:
        conn.execute(
            text("UPDATE bootstrap_codes SET expires_at = :p"),
            {"p": iso(utcnow() - timedelta(minutes=1))},
        )
    r = client.post("/api/auth/passkey/register/begin", json={"bootstrap_code": code})
    assert r.status_code == 401


def test_second_passkey_from_session(
    client: TestClient, hub: HubContext, phone: SoftAuthenticator
) -> None:
    _register(client, phone, _code(hub))
    backup_key = SoftAuthenticator("hub.example.ts.net", ORIGIN)
    # une session seule n'enrôle rien de durable (audit M16) : la passkey en place signe
    alone = client.post("/api/auth/passkey/register/begin", json={"bootstrap_code": None})
    assert (alone.status_code, alone.json()["type"]) == (403, "auth.confirm_required")
    r = _register(client, backup_key, None, name="clé de secours", holder=phone)
    assert r.status_code == 200, r.text
    assert r.json()["passkeys"] == 2
    client.post("/api/auth/logout")
    client.cookies.clear()
    assert _login(client, backup_key).status_code == 200


def test_a_passkey_is_removed_under_face_id_never_the_last(
    client: TestClient, hub: HubContext, phone: SoftAuthenticator
) -> None:
    _register(client, phone, _code(hub))
    backup_key = SoftAuthenticator("hub.example.ts.net", ORIGIN)
    _register(client, backup_key, None, name="clé de secours", holder=phone)
    ids = [k["id"] for k in client.get("/api/auth/passkeys").json()["items"]]
    assert ids == [phone.id, backup_key.id]
    # sans signature valable : refusé ; un défi de connexion ne vaut pas un défi de retrait
    bad = client.request(
        "DELETE",
        f"/api/auth/passkeys/{backup_key.id}",
        json={"challenge_id": "x", "credential": {"id": phone.id}},
    )
    assert bad.status_code == 401
    gone = client.request(
        "DELETE", f"/api/auth/passkeys/{backup_key.id}", json=_confirm(client, phone)
    )
    assert gone.status_code == 204, gone.text
    assert [k["id"] for k in client.get("/api/auth/passkeys").json()["items"]] == [phone.id]
    assert _login(client, backup_key).status_code == 401  # retirée : ne connecte plus
    last = client.request("DELETE", f"/api/auth/passkeys/{phone.id}", json=_confirm(client, phone))
    assert (last.status_code, last.json()["type"]) == (409, "auth.last_passkey")


def test_removing_my_own_passkey_closes_my_session(
    client: TestClient, hub: HubContext, phone: SoftAuthenticator
) -> None:
    _register(client, phone, _code(hub))
    backup_key = SoftAuthenticator("hub.example.ts.net", ORIGIN)
    _register(client, backup_key, None, name="clé de secours", holder=phone)
    gone = client.request("DELETE", f"/api/auth/passkeys/{phone.id}", json=_confirm(client, phone))
    assert gone.status_code == 204
    assert client.get("/api/auth/passkeys").status_code == 401


def test_session_expires_after_12_hours(
    client: TestClient, hub: HubContext, phone: SoftAuthenticator
) -> None:
    _register(client, phone, _code(hub))
    assert client.get("/api/auth/passkeys").status_code == 200
    with hub.core.engine.begin() as conn:
        conn.execute(
            text("UPDATE sessions SET expires_at = :p"), {"p": iso(utcnow() - timedelta(seconds=1))}
        )
    r = client.get("/api/auth/passkeys")
    assert (r.status_code, r.json()["type"]) == (401, "auth.invalid")


def test_bad_assertions_are_refused(
    client: TestClient, hub: HubContext, phone: SoftAuthenticator
) -> None:
    _register(client, phone, _code(hub))
    client.cookies.clear()
    assert _login(client, phone, origin="https://evil.example").status_code == 401
    assert _login(client, phone, user_verified=False).status_code == 401
    stranger = SoftAuthenticator("hub.example.ts.net", ORIGIN)
    assert _login(client, stranger).status_code == 401
    # un défi ne sert qu'une fois
    begin = client.post("/api/auth/passkey/login/begin").json()
    cred = phone.sign(begin["options"])
    body = {"challenge_id": begin["challenge_id"], "credential": cred}
    assert client.post("/api/auth/passkey/login/finish", json=body).status_code == 200
    r = client.post("/api/auth/passkey/login/finish", json=body)
    assert (r.status_code, r.json()["type"]) == (401, "auth.challenge_expired")
    r = client.post("/api/auth/passkey/login/finish", json={"challenge_id": "x", "credential": {}})
    assert r.status_code == 401


def test_register_with_wrong_origin_keeps_code(
    client: TestClient, hub: HubContext, phone: SoftAuthenticator
) -> None:
    code = _code(hub)
    begin = client.post("/api/auth/passkey/register/begin", json={"bootstrap_code": code}).json()
    r = client.post(
        "/api/auth/passkey/register/finish",
        json={
            "challenge_id": begin["challenge_id"],
            "credential": phone.register(begin["options"], origin="https://evil.example"),
            "bootstrap_code": code,
        },
    )
    assert (r.status_code, r.json()["type"]) == (401, "auth.passkey_invalid")
    assert _register(client, phone, code).status_code == 200  # le code n'a pas été consommé


def test_login_rate_limit(client: TestClient, hub: HubContext) -> None:
    for _ in range(10):
        assert client.post("/api/auth/passkey/login/begin").status_code == 200
    r = client.post("/api/auth/passkey/login/begin")
    assert (r.status_code, r.json()["type"]) == (429, "rate_limited")
    assert r.headers["retry-after"] == "60"
