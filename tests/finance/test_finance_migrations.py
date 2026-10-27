"""Section 9 pour finance.db : base vide → head, déclencheurs, ajout seul, empreintes."""

import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError

from hub.core.db import backup, begin_immediate, make_engine
from hub.domains.finance import hashing, ledger
from hub.domains.finance.domain import FinanceDomain
from tests.finance.conftest import ready_account

pytestmark = pytest.mark.migrations

PROTECTED = (*hashing.PROTECTED, "journal")


def _names(finance: FinanceDomain, kind: str) -> set[str]:
    with finance.engine().connect() as conn:
        return {
            r[0]
            for r in conn.execute(
                text("SELECT name FROM sqlite_master WHERE type = :t"), {"t": kind}
            )
        }


def test_upgrade_head_on_empty_base(finance: FinanceDomain) -> None:
    assert finance.is_current()
    tables = _names(finance, "table")
    assert tables >= {
        "currencies",
        "accounts",
        "imports",
        "import_statements",
        "entries",
        "categories",
        "rules",
        "rules_meta",
        "fx_rates",
        "compositions",
        "transfer_links",
        "recurring",
        "entries_fts",
        "notes_fts",
        *PROTECTED,
    }
    triggers = _names(finance, "trigger")
    for t in PROTECTED:
        assert {f"{t}_no_update", f"{t}_no_delete"} <= triggers
    assert {"v_entry_category", "v_entry_allocation", "v_balances", "v_taggings"} <= _names(
        finance, "view"
    )
    finance.migrate()  # idempotent
    assert finance.health().ok


def test_seed_data(finance: FinanceDomain) -> None:
    with finance.engine().connect() as conn:
        assert conn.execute(text("SELECT exponent FROM currencies WHERE code='CHF'")).scalar() == 2
        assert conn.execute(
            text("SELECT grp FROM categories WHERE id='transfer-own'")
        ).scalar() == ("transfer")
        # 0004_rules : règles de départ de bcf_aggregate.py ; 0005_viac : règles VIAC ;
        # 0006_wealth : règles IBKR
        assert conn.execute(text("SELECT version FROM rules_meta")).scalar() == 4
        seeds = conn.execute(text("SELECT count(*) FROM rules WHERE id LIKE 'seed-%'")).scalar()
        assert seeds is not None
        assert seeds > 250
        assert conn.execute(text("SELECT name FROM categories WHERE id='voyages'")).scalar() == (
            "Vacances"
        )


def seed_every_table(finance: FinanceDomain) -> None:
    """Une ligne dans chaque table protégée, par `ledger.append` (journal compris)."""
    account = ready_account(finance)
    at = "2026-10-27T10:00:00.000Z"
    with begin_immediate(finance.engine()) as conn:
        seq = conn.execute(text("SELECT seq FROM entries")).scalar_one()
        imp = "imp1"
        conn.execute(
            text(
                "INSERT INTO imports (id, source, file_sha256, file_name, received_at, status, "
                "updated_at) VALUES ('imp1', 'camt053', 'h', 'f.xml', :at, 'applied', :at)"
            ),
            {"at": at},
        )
        cat = ledger.append(
            conn,
            "categorizations",
            {
                "entry_seq": seq,
                "category_id": "divers",
                "source": "user",
                "rule_id": None,
                "proposal_id": "p1",
                "created_at": at,
            },
        )
        ledger.append(
            conn,
            "categorization_lines",
            {"categorization_seq": cat, "line": 1, "category_id": "divers", "amount_minor": 1},
        )
        ledger.append(
            conn,
            "notes",
            {
                "entry_seq": seq,
                "text": "Note",
                "search_text": "note",
                "proposal_id": None,
                "created_at": at,
            },
        )
        ledger.append(
            conn,
            "checkpoints",
            {
                "account_id": account.id,
                "on_date": "2026-10-01",
                "kind": "CLBD",
                "amount_minor": 1,
                "import_id": imp,
            },
        )
        ledger.append(
            conn,
            "budgets",
            {
                "category_id": "divers",
                "monthly_minor": 100,
                "currency": "CHF",
                "valid_from": "2026-10-01",
                "proposal_id": None,
                "created_at": at,
            },
        )
        ledger.append(conn, "tags", {"id": "t", "name": "T", "kind": "other", "created_at": at})
        ledger.append(
            conn,
            "taggings",
            {"entry_seq": seq, "tag_id": "t", "active": 1, "proposal_id": None, "created_at": at},
        )
        ledger.append(
            conn,
            "applied_proposals",
            {"proposal_id": "p1", "kind": "x", "result_json": "{}", "applied_at": at},
        )
        ledger.append(
            conn,
            "trades",
            {
                "account_id": account.id,
                "trade_date": "2026-10-02",
                "isin": "CH0000000011",
                "quantity": "1.5",
                "amount_minor": 15000,
                "currency": "CHF",
                "dedup_key": "k",
                "import_id": imp,
                "created_at": at,
            },
        )
        ledger.append(
            conn,
            "holdings",
            {
                "account_id": account.id,
                "on_date": "2026-10-02",
                "isin": "CH0000000011",
                "quantity": "1.5",
                "value_minor": 15000,
                "currency": "CHF",
                "cost_price": "100",
                "import_id": imp,
                "created_at": at,
            },
        )
        ledger.append(
            conn,
            "prices",
            {
                "isin": "CH0000000011",
                "on_date": "2026-10-02",
                "price": "100",
                "currency": "CHF",
                "source": "viac_report",
                "import_id": imp,
                "created_at": at,
            },
        )
        ledger.append_event(conn, "test", "hub:finance:entry:x")


@pytest.mark.parametrize("table", PROTECTED)
def test_protected_tables_refuse_update_and_delete(finance: FinanceDomain, table: str) -> None:
    seed_every_table(finance)
    for sql in (f"UPDATE {table} SET rowid = rowid", f"DELETE FROM {table}"):
        with (
            pytest.raises(DatabaseError, match=r"ledger\.append_only"),
            finance.engine().begin() as c,
        ):
            c.execute(text(sql))
    assert finance.verify_ledger().ok


def test_insert_or_replace_on_existing_dedup_key_is_refused(finance: FinanceDomain) -> None:
    ready_account(finance)
    with finance.engine().connect() as conn:
        row = conn.execute(text("SELECT * FROM entries")).mappings().one()
    cols = ", ".join(row)
    marks = ", ".join(f":{c}" for c in row)
    values = {**row, "seq": None}  # nouvelle ligne, même dedup_key : conflit UNIQUE
    with pytest.raises(DatabaseError, match=r"ledger\.append_only"), finance.engine().begin() as c:
        c.execute(text(f"INSERT OR REPLACE INTO entries ({cols}) VALUES ({marks})"), values)


def test_hash_fields_match_columns(finance: FinanceDomain) -> None:
    """Une colonne hors de la liste de la version courante (ou l'inverse) fait échouer."""
    with finance.engine().connect() as conn:
        for table in hashing.PROTECTED:
            cols = {r[1] for r in conn.execute(text(f"PRAGMA table_info({table})"))}
            fields = set(hashing.FIELDS[table][hashing.current_version(table)])
            assert cols - hashing.not_hashed(table) == fields, table


def test_upgrade_on_reference_base_keeps_ledger_valid(tmp_path: Path) -> None:
    """Base fictive à la version précédente (0001), montée à head : verify-ledger passe."""
    from hub.core.migrations import runner
    from hub.domains.finance.domain import MIGRATIONS
    from tests.finance.conftest import finance_settings

    settings = finance_settings(tmp_path)
    domain = FinanceDomain(settings)
    runner.upgrade(MIGRATIONS, domain.path, "0001_ledger")
    ready_account(domain)
    runner.upgrade(MIGRATIONS, domain.path)
    assert domain.verify().ok
    domain.engine().dispose()


def test_journal_cannot_be_rewritten_through_a_copy_without_detection(
    finance: FinanceDomain, tmp_path: Path
) -> None:
    ready_account(finance)
    assert finance.verify_ledger().ok
    copy = tmp_path / "copy.db"
    backup(finance.engine(), copy)
    raw = sqlite3.connect(copy)
    raw.execute("DROP TRIGGER entries_no_update")
    raw.execute("UPDATE entries SET amount_minor = amount_minor + 1")
    raw.commit()
    raw.close()
    engine = make_engine(copy)
    with engine.connect() as conn:
        result = ledger.verify(conn)
    engine.dispose()
    assert not result.ok
    assert any("altérée" in e for e in result.errors)
    with begin_immediate(finance.engine()) as conn:
        assert ledger.verify(conn).ok
