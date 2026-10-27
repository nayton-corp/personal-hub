"""Section 9 : base vide → head, déclencheurs présents, ajout seul garanti."""

from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError, IntegrityError

from hub.core.coredb import CoreDB, audit

pytestmark = pytest.mark.migrations

EXPECTED_TABLES = {
    "tokens",
    "passkeys",
    "sessions",
    "bootstrap_codes",
    "proposals",
    "audit",
    "collector_runs",
    "collector_state",
    "links",
    "approval_policies",
    "webauthn_challenges",
    "rate_limits",
    "event_cursors",
    "alembic_version",
}
PROTECTED = ("audit", "links")


@pytest.fixture
def core(tmp_path: Path) -> CoreDB:
    db = CoreDB(tmp_path / "core.db")
    db.migrate()
    yield db
    db.dispose()


def test_upgrade_head_on_empty_base(core: CoreDB) -> None:
    assert core.is_current()
    with core.engine.connect() as conn:
        tables = {
            r[0] for r in conn.execute(text("SELECT name FROM sqlite_master WHERE type = 'table'"))
        }
        triggers = {
            r[0]
            for r in conn.execute(text("SELECT name FROM sqlite_master WHERE type = 'trigger'"))
        }
    assert tables >= EXPECTED_TABLES
    assert "idempotency" not in tables  # supprimée par la revue d'architecture
    for t in PROTECTED:
        assert {f"{t}_no_update", f"{t}_no_delete"} <= triggers


def test_upgrade_is_idempotent(core: CoreDB) -> None:
    core.migrate()
    assert core.is_current()


def _seed(core: CoreDB) -> None:
    with core.engine.begin() as conn:
        audit(conn, "system:test", "test.seed", None, "ok")
        conn.execute(
            text(
                "INSERT INTO links (seq, from_urn, to_urn, rel, created_by, created_at) "
                "VALUES (1, 'hub:a:x:1', 'hub:b:y:2', 'pays', 'system:test', '2026-10-27')"
            )
        )


@pytest.mark.parametrize("table", PROTECTED)
@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE {t} SET seq = seq",
        "DELETE FROM {t}",
        "INSERT OR REPLACE INTO {t} SELECT * FROM {t}",
        "REPLACE INTO {t} SELECT * FROM {t}",
    ],
)
def test_protected_tables_are_append_only(core: CoreDB, table: str, statement: str) -> None:
    _seed(core)
    with pytest.raises(DatabaseError, match=r"ledger\.append_only"), core.engine.begin() as conn:
        conn.execute(text(statement.format(t=table)))
    with core.engine.connect() as conn:
        assert conn.execute(text(f"SELECT count(*) FROM {table}")).scalar() == 1


def test_proposal_status_and_single_pending(core: CoreDB) -> None:
    row = (
        "INSERT INTO proposals (id, domain, kind, params_json, params_hash, preview_json, "
        "fingerprint, status, created_by, created_at, expires_at) VALUES "
        "(:id, 'demo', 'k', '{}', 'h', '{}', 'f', :s, 'system:test', 'a', 'b')"
    )
    with core.engine.begin() as conn:
        conn.execute(text(row), {"id": "1", "s": "pending"})
        conn.execute(text(row), {"id": "2", "s": "applied"})  # même empreinte, autre statut : ok
    with pytest.raises(IntegrityError), core.engine.begin() as conn:
        conn.execute(text(row), {"id": "3", "s": "pending"})
    with pytest.raises(IntegrityError), core.engine.begin() as conn:
        conn.execute(text(row), {"id": "4", "s": "done"})
