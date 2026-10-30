"""Chantier S8 : aucun jeton sans date de fin ; un jeton fini ne s'utilise plus, se renouvelle
par rotation, et la tâche de nuit prévient 14 jours avant, une seule fois."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from hub.core import maintenance, notify, tokens
from hub.core.context import HubContext
from hub.core.notify import Message, Notifier
from hub.kernel.clock import parse_iso
from hub.platform import migrations as runner
from tests.conftest import bearer

CORE = Path(__file__).resolve().parents[1] / "hub" / "core" / "migrations"


def _age(hub: HubContext, token_id: str, expires_at: str) -> None:
    with hub.core.engine.begin() as conn:
        conn.execute(
            text("UPDATE tokens SET expires_at = :e WHERE id = :i"),
            {"e": expires_at, "i": token_id},
        )


def test_no_token_without_an_end(hub: HubContext) -> None:
    with hub.core.engine.begin() as conn:
        for days in (0, tokens.MAX_DAYS + 1):
            with pytest.raises(tokens.ScopeError, match="durée"):
                tokens.create(conn, "x", ["aggregates"], "system:test", days=days)
        info, _ = tokens.create(conn, "x", ["aggregates"], "system:test", days=30)
    assert info.expires_at[:4] >= info.created_at[:4]
    assert info.state == "actif"


def test_an_expired_token_is_refused(hub: HubContext, client: TestClient) -> None:
    with hub.core.engine.begin() as conn:
        info, secret = tokens.create(conn, "brain", ["demo:read"], "system:test", days=30)
    assert client.get("/api/demo/items", headers=bearer(secret)).status_code == 200
    _age(hub, info.id, "2020-01-01T00:00:00.000Z")
    assert client.get("/api/demo/items", headers=bearer(secret)).status_code == 401
    with hub.core.engine.connect() as conn:
        assert tokens.list_all(conn)[0].state == "expiré"


def test_rotation_keeps_scopes_and_lifetime_and_revokes_the_old(hub: HubContext) -> None:
    with hub.core.engine.begin() as conn:
        old, old_secret = tokens.create(conn, "brain-mac", ["brain=demo"], "system:test", days=60)
        new, new_secret = tokens.rotate(conn, old.id, "system:test") or (None, "")
        assert new is not None
        assert (new.name, new.scopes) == (old.name, old.scopes)
        # même durée de vie, comptée depuis la rotation (la même milliseconde en CI rapide)
        assert new.expires_at >= old.expires_at
        assert parse_iso(new.expires_at) - parse_iso(new.created_at) == (
            parse_iso(old.expires_at) - parse_iso(old.created_at)
        )
        assert tokens.verify(conn, old_secret) is None
        assert tokens.verify(conn, new_secret) is not None
        assert tokens.rotate(conn, old.id, "system:test") is None  # déjà révoqué
        assert tokens.rotate(conn, "ghost", "system:test") is None
        short, _ = tokens.rotate(conn, new.id, "system:test", days=7) or (None, "")
    assert short is not None
    assert parse_iso(short.expires_at) - parse_iso(short.created_at) < (
        parse_iso(new.expires_at) - parse_iso(new.created_at)
    )


def test_the_night_warns_once_14_days_before(
    hub: HubContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[Message] = []
    hub.notifier = Notifier(hub.settings, sender=lambda _url, m: sent.append(m))
    monkeypatch.setattr(notify, "topic", lambda _settings: "sujet")
    with hub.core.engine.begin() as conn:
        soon, _ = tokens.create(conn, "brain-mac", ["brain"], "system:test", days=10)
        tokens.create(conn, "later", ["brain"], "system:test", days=60)
        tokens.create(conn, "collector-api", ["collector"], "system:test", days=3)
    assert maintenance.nightly(hub)["tokens_warned"] == 2
    assert maintenance.nightly(hub)["tokens_warned"] == 0  # une seule alerte par jeton
    svc, brain = sent
    assert svc.title.startswith("Jeton « collector-api » : fin le ")
    assert "secrets/collector-api.enc.yaml" in svc.body
    assert brain.body == f"hub token rotate {soon.id}"
    assert all(m.tags == "key" for m in sent)


def test_tokens_of_before_get_one_year(tmp_path: Path) -> None:
    db = tmp_path / "core.db"
    runner.upgrade(CORE, db, "0006_collector_refresh")
    with sqlite3.connect(db) as raw:
        raw.execute(
            "INSERT INTO tokens (id, name, scopes, secret_hash, created_at) VALUES "
            "('t1', 'brain-mac', 'finance:read', 'h', '2026-10-27T10:00:00.000Z')"
        )
    runner.upgrade(CORE, db)
    with sqlite3.connect(db) as raw:
        row = raw.execute("SELECT expires_at, warned_at FROM tokens").fetchone()
    assert row == ("2027-10-27T10:00:00.000Z", None)
