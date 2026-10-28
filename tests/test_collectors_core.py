"""État des collecteurs dans core.db et routes (lot 5, table des échecs de la section 8)."""

from __future__ import annotations

import threading
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from hub.core import collectors
from hub.core.clock import iso, now_iso, utcnow
from hub.core.context import HubContext
from hub.core.errors import Problem
from hub.core.notify import Message
from tests.conftest import bearer


def _run(outcome: str, kind: str = "run", detail: str | None = None) -> collectors.Run:
    now = now_iso()
    return collectors.Run(kind, outcome, now, now, 1 if outcome == "ok" else 0, detail)  # type: ignore[arg-type]


def record(hub: HubContext, outcome: str, **kw: str) -> collectors.Recorded:
    with hub.core.engine.begin() as conn:
        return collectors.record(conn, "bcf", _run(outcome, **kw), "system:test")


def test_success_resets_failures(hub: HubContext) -> None:
    r = record(hub, "selector_missing", detail="export.button")
    assert r.state.consecutive_failures == 1
    assert r.state.mode == "enabled"
    assert r.alerts
    assert "export.button" in r.alerts[0].body
    r = record(hub, "ok")
    assert r.state.consecutive_failures == 0
    assert r.alerts == []
    assert r.state.last_success_at is not None


def test_two_hard_failures_degrade(hub: HubContext) -> None:
    record(hub, "selector_missing")
    r = record(hub, "unknown")
    assert r.state.mode == "degraded"
    assert "suspendue" in r.alerts[0].body


def test_auth_error_degrades_at_once(hub: HubContext) -> None:
    r = record(hub, "auth_error")
    assert r.state.mode == "degraded"
    assert r.alerts[0].priority == "urgent"


def test_push_timeout_alerts_once_a_day_and_never_degrades(hub: HubContext) -> None:
    first = record(hub, "auth_pending_timeout")
    second = record(hub, "auth_pending_timeout")
    assert len(first.alerts) == 1
    assert second.alerts == []
    assert second.state.mode == "enabled"
    assert second.state.consecutive_failures == 0


def test_site_unavailable_alerts_on_third_in_a_row(hub: HubContext) -> None:
    alerts = [len(record(hub, "site_unavailable").alerts) for _ in range(4)]
    assert alerts == [0, 0, 1, 0]


def test_disabled_collector_never_alerts_nor_changes(hub: HubContext) -> None:
    with hub.core.engine.begin() as conn:
        collectors.set_mode(conn, "bcf", "disabled", "system:test")
    r = record(hub, "auth_error")
    assert r.state.mode == "disabled"
    assert r.alerts == []


def test_enable_requires_successful_last_run(hub: HubContext) -> None:
    record(hub, "auth_error")
    with hub.core.engine.begin() as conn, pytest.raises(Problem) as exc:
        collectors.set_mode(conn, "bcf", "enabled", "system:test")
    assert exc.value.type == "collector.check_required"
    with hub.core.engine.begin() as conn:
        collectors.request_check(conn, "bcf", "system:test")
        assert collectors.get(conn, "bcf").check_requested_at is not None
    r = record(hub, "ok", kind="check")
    assert r.state.check_requested_at is None
    assert r.state.mode == "degraded"  # le retour reste manuel
    with hub.core.engine.begin() as conn:
        state = collectors.set_mode(conn, "bcf", "enabled", "system:test")
    assert state.mode == "enabled"
    assert state.consecutive_failures == 0


def test_degraded_is_not_a_user_mode(hub: HubContext) -> None:
    with hub.core.engine.begin() as conn, pytest.raises(Problem):
        collectors.set_mode(conn, "bcf", "degraded", "system:test")


def test_detail_keeps_step_and_selector_only() -> None:
    assert collectors.clean_detail("Export.Button") == "export.button"
    assert collectors.clean_detail("CHF 1'234.50 <b>") == "chf 1?234.50 ?b?"
    assert collectors.clean_detail(None) is None


def test_unknown_collector(hub: HubContext) -> None:
    with hub.core.engine.begin() as conn, pytest.raises(Problem) as exc:
        collectors.get(conn, "ubs")
    assert exc.value.type == "collector.unknown"


def test_link_code_is_given_once(hub: HubContext) -> None:
    state = collectors.new_state()
    with hub.core.engine.begin() as conn:
        collectors.register_link(conn, "revolut", state)
        assert collectors.take_code(conn, "revolut", state) is None
        assert not collectors.receive_code(conn, "revolut", "x" * 20, "c0de")
        assert collectors.receive_code(conn, "revolut", state, "c0de")
        assert not collectors.receive_code(conn, "revolut", state, "other")
        assert collectors.take_code(conn, "revolut", state) == "c0de"
        with pytest.raises(Problem):
            collectors.take_code(conn, "revolut", state)


def test_expired_link_is_refused_and_purged(hub: HubContext) -> None:
    state = collectors.new_state()
    past = iso(utcnow() - timedelta(minutes=1))
    with hub.core.engine.begin() as conn:
        collectors.register_link(conn, "revolut", state)
        conn.exec_driver_sql("UPDATE collector_links SET expires_at = ?", (past,))
        assert not collectors.receive_code(conn, "revolut", state, "c0de")
        assert collectors.purge_links(conn) == 1


# --- routes ---------------------------------------------------------------------------------


@pytest.fixture
def sent(hub: HubContext, monkeypatch: pytest.MonkeyPatch) -> list[Message]:
    out: list[Message] = []
    monkeypatch.setattr(hub.notifier, "sender", lambda _url, msg: out.append(msg))
    monkeypatch.setattr("hub.core.notify.topic", lambda _s: "topic-test")
    return out


def _body(outcome: str, **extra: object) -> dict[str, object]:
    now = now_iso()
    return {"outcome": outcome, "started_at": now, "ended_at": now, **extra}


def test_run_route_needs_collector_scope(client: TestClient, make_token) -> None:  # type: ignore[no-untyped-def]
    brain = make_token("brain")
    r = client.post("/api/collectors/bcf/runs", json=_body("ok"), headers=bearer(brain))
    assert r.status_code == 403
    assert client.get("/api/collectors", headers=bearer(brain)).status_code == 403


def test_run_route_records_and_alerts(
    client: TestClient,
    make_token,  # type: ignore[no-untyped-def]
    sent: list[Message],
) -> None:
    token = bearer(make_token("collector"))
    r = client.post("/api/collectors/bcf/runs", json=_body("auth_error"), headers=token)
    assert r.status_code == 201
    assert r.json()["mode"] == "degraded"
    assert r.json()["can_enable"] is False
    assert [m.priority for m in sent] == ["urgent"]
    runs = client.get("/api/collectors/bcf/runs", headers=token).json()["items"]
    assert runs[0]["outcome"] == "auth_error"
    assert client.get("/api/collectors/ubs", headers=token).status_code == 404


def test_run_route_refuses_bad_payload(client: TestClient, make_token) -> None:  # type: ignore[no-untyped-def]
    token = bearer(make_token("collector"))
    r = client.post("/api/collectors/bcf/runs", json=_body("boom"), headers=token)
    assert r.status_code == 422
    r = client.post("/api/collectors/bcf/runs", json=_body("ok", started_at="hier"), headers=token)
    assert r.status_code == 422


def test_notify_route(client: TestClient, make_token, sent: list[Message]) -> None:  # type: ignore[no-untyped-def]
    token = bearer(make_token("collector"))
    r = client.post("/api/collectors/bcf/notify", json={"event": "auth_pending"}, headers=token)
    assert r.json() == {"sent": True}
    r = client.post(
        "/api/collectors/revolut/notify", json={"event": "consent_expiring"}, headers=token
    )
    assert r.json() == {"sent": True}
    assert "valide" in sent[0].body.lower()
    assert all("CHF" not in m.body for m in sent)


def test_notify_without_topic_sends_nothing(client: TestClient, make_token) -> None:  # type: ignore[no-untyped-def]
    token = bearer(make_token("collector"))
    r = client.post("/api/collectors/bcf/notify", json={"event": "auth_pending"}, headers=token)
    assert r.json() == {"sent": False}


def test_mode_and_check_routes_are_app_only(client: TestClient, make_token) -> None:  # type: ignore[no-untyped-def]
    token = bearer(make_token("collector"))
    assert (
        client.post("/api/collectors/bcf/mode", json={"mode": "disabled"}, headers=token)
    ).status_code == 403
    assert client.post("/api/collectors/bcf/check", headers=token).status_code == 403


def test_callback_flow(client: TestClient, make_token) -> None:  # type: ignore[no-untyped-def]
    token = bearer(make_token("collector"))
    state = collectors.new_state()
    r = client.post("/api/collectors/revolut/links", json={"state": state}, headers=token)
    assert r.status_code == 201
    assert (
        client.get(f"/api/collectors/revolut/links/{state}", headers=token).json()["code"] is None
    )
    page = client.get("/api/collectors/revolut/callback", params={"state": state, "code": "abc"})
    assert page.status_code == 200
    assert "reçue" in page.text
    again = client.get("/api/collectors/revolut/callback", params={"state": state, "code": "x"})
    assert again.status_code == 400
    assert client.get(f"/api/collectors/revolut/links/{state}", headers=token).json()["code"] == (
        "abc"
    )
    refused = client.get(
        "/api/collectors/revolut/callback",
        params={"state": state, "error": "access_denied", "error_description": "Annulé"},
    )
    assert "refusée (access_denied) : Annulé" in refused.text
    assert client.get(f"/api/collectors/revolut/links/{state}", headers=token).status_code == 404


def test_notifier_retries_a_passing_network_failure(
    hub: HubContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("hub.core.notify.topic", lambda _s: "topic-test")
    pauses: list[int] = []
    calls: list[str] = []

    def flaky(url: str, _msg: Message) -> None:
        calls.append(url)
        if len(calls) < 3:
            raise OSError("dns")

    monkeypatch.setattr(hub.notifier, "sender", flaky)
    monkeypatch.setattr(hub.notifier, "pause", pauses.append)
    assert hub.notifier.send(Message("Personal Hub", "test"))
    assert (len(calls), pauses) == (3, [2, 5])

    monkeypatch.setattr(hub.notifier, "sender", lambda _u, _m: (_ for _ in ()).throw(OSError()))
    assert not hub.notifier.send(Message("Personal Hub", "test"))


def test_simultaneous_collectors_do_not_lock_the_database(client: TestClient, make_token) -> None:  # type: ignore[no-untyped-def]
    # les démons des collecteurs appellent l'API dans la même milliseconde, chaque minute pile ;
    # la vérification du jeton écrit last_used_at et ne doit pas finir en « database is locked »
    secrets = [make_token("collector", name=f"c{i}") for i in range(6)]
    barrier = threading.Barrier(len(secrets))
    statuses: list[int] = []

    def tick(secret: str) -> None:
        for _ in range(15):
            barrier.wait(timeout=30)
            try:
                r = client.get("/api/collectors/bcf", headers=bearer(secret))
                statuses.append(r.status_code)
            except Exception:  # le client de test relance l'erreur du serveur
                statuses.append(500)

    workers = [threading.Thread(target=tick, args=(s,)) for s in secrets]
    for w in workers:
        w.start()
    for w in workers:
        w.join()
    assert set(statuses) == {200}
