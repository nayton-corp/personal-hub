"""L1-02 : écriture au registre, chaîne du journal, verify-ledger et versions d'empreinte."""

import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import text

from hub.core.db import backup, begin_immediate, make_engine
from hub.domains.finance import hashing, ledger
from hub.domains.finance.domain import FinanceDomain
from tests.finance.conftest import ready_account


def _entry(account_id: str, n: int) -> ledger.NewEntry:
    return ledger.NewEntry(
        account_id=account_id,
        booking_date=f"2026-10-{n % 28 + 1:02d}",
        amount_minor=-100 * n,
        currency="CHF",
        dedup_key=ledger.dedup_hash(f"test|{n}"),
        counterparty="Épicerie Fictive",
        label="Achat",
    )


def _tampered(finance: FinanceDomain, tmp_path: Path, *sql: str) -> ledger.VerifyResult:
    copy = tmp_path / "copy.db"
    backup(finance.engine(), copy)
    raw = sqlite3.connect(copy)
    for statement in sql:
        raw.execute(statement)
    raw.commit()
    raw.close()
    engine = make_engine(copy)
    try:
        with engine.connect() as conn:
            return ledger.verify(conn)
    finally:
        engine.dispose()


@pytest.fixture
def filled(finance: FinanceDomain) -> FinanceDomain:
    account = ready_account(finance)
    with begin_immediate(finance.engine()) as conn:
        for n in range(1, 6):
            ledger.append_entry(conn, _entry(account.id, n))
    return finance


def test_chain_verifies_and_counts(filled: FinanceDomain) -> None:
    result = filled.verify_ledger()
    assert result.ok, result.errors
    assert result.rows["entries"] == 6  # ouverture + 5
    assert result.links == 6
    with filled.engine().connect() as conn:
        first = conn.execute(text("SELECT prev_hash FROM journal ORDER BY seq LIMIT 1")).scalar()
        ids = conn.execute(text("SELECT id, dedup_key FROM entries")).fetchall()
        search = conn.execute(text("SELECT search_text FROM entries WHERE seq = 2")).scalar()
    assert first == hashing.GENESIS
    assert all(i == ledger.entry_id(k) for i, k in ids)  # identifiant déterministe
    assert search == "epicerie fictive achat"


def test_altered_row_is_detected(filled: FinanceDomain, tmp_path: Path) -> None:
    result = _tampered(
        filled,
        tmp_path,
        "DROP TRIGGER entries_no_update",
        "UPDATE entries SET label = 'autre' WHERE seq = 3",
    )
    assert not result.ok
    assert result.errors == ["journal 3 (entries 3) : ligne altérée"]


def test_altered_journal_and_missing_rows_are_detected(
    filled: FinanceDomain, tmp_path: Path
) -> None:
    result = _tampered(
        filled,
        tmp_path,
        "DROP TRIGGER journal_no_update",
        "UPDATE journal SET row_hash = '00' WHERE seq = 2",
    )
    assert any("maillon altéré" in e for e in result.errors)
    result = _tampered(
        filled,
        tmp_path,
        "DROP TRIGGER journal_no_delete",
        "DELETE FROM journal WHERE seq = 4",
    )
    assert any("maillon précédent" in e for e in result.errors)
    assert any("hors journal" in e for e in result.errors)
    result = _tampered(
        filled,
        tmp_path,
        "DROP TRIGGER entries_no_delete",
        "PRAGMA foreign_keys=OFF",
        "DELETE FROM entries WHERE seq = 5",
    )
    assert any("ligne absente" in e for e in result.errors)
    result = _tampered(
        filled,
        tmp_path,
        "INSERT INTO tags (id, name, kind, created_at, hash_v) VALUES ('x', 'x', 'other', 'x', 1)",
    )
    assert result.errors == ["tags : 1 ligne(s) hors journal"]


def test_unknown_hash_version_is_reported(filled: FinanceDomain, tmp_path: Path) -> None:
    result = _tampered(
        filled,
        tmp_path,
        "DROP TRIGGER entries_no_update",
        "UPDATE entries SET hash_v = 9 WHERE seq = 2",
    )
    assert result.errors == ["journal 2 (entries 2) : version d'empreinte inconnue"]


def test_adding_a_column_creates_next_hash_version(
    filled: FinanceDomain, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Revue d'architecture : les lignes anciennes se vérifient avec leur propre liste."""
    v1 = hashing.FIELDS["tags"][1]
    monkeypatch.setitem(hashing.FIELDS, "tags", {1: v1, 2: (*v1, "color")})
    with begin_immediate(filled.engine()) as conn:
        conn.execute(text("ALTER TABLE tags ADD COLUMN color TEXT"))
    with begin_immediate(filled.engine()) as conn:
        ledger.append(
            conn,
            "tags",
            {"id": "a", "name": "A", "kind": "other", "created_at": "x", "color": None},
        )
    # ligne v1 écrite avant la colonne, ligne v2 après : la chaîne reste verte
    monkeypatch.setitem(hashing.FIELDS, "tags", {1: v1})
    with begin_immediate(filled.engine()) as conn:
        ledger.append(conn, "tags", {"id": "b", "name": "B", "kind": "other", "created_at": "x"})
    monkeypatch.setitem(hashing.FIELDS, "tags", {1: v1, 2: (*v1, "color")})
    with begin_immediate(filled.engine()) as conn:
        ledger.append(
            conn,
            "tags",
            {"id": "c", "name": "C", "kind": "other", "created_at": "x", "color": "red"},
        )
    with filled.engine().connect() as conn:
        versions = dict(conn.execute(text("SELECT id, hash_v FROM tags")).fetchall())
    assert versions == {"a": 2, "b": 1, "c": 2}
    assert filled.verify_ledger().ok


def test_append_refuses_unknown_table_and_missing_fields(finance: FinanceDomain) -> None:
    with begin_immediate(finance.engine()) as conn:
        with pytest.raises(ledger.LedgerError, match="non protégée"):
            ledger.append(conn, "accounts", {})
        with pytest.raises(ledger.LedgerError, match="champs absents"):
            ledger.append(conn, "tags", {"id": "x"})
    with pytest.raises(ValueError, match="version"):
        hashing.row_hash("tags", {}, 7)


def test_nightly_logs_failure(filled: FinanceDomain, monkeypatch: pytest.MonkeyPatch) -> None:
    filled.nightly()  # chaîne valide
    monkeypatch.setattr(
        filled, "verify_ledger", lambda: ledger.VerifyResult(ok=False, errors=["x"])
    )
    filled.nightly()
    assert not filled.verify().ok
