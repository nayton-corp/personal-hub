"""Section 9 pour finance.db : base vide → head, déclencheurs, ajout seul, empreintes."""

import json
import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError

from hub.domains.finance.classement.app import packs
from hub.domains.finance.domain import FinanceDomain
from hub.domains.finance.registre.app import ledger
from hub.domains.finance.registre.model import hashing
from hub.platform.db import backup, begin_immediate, make_engine
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
        "crypto_moves",
        "crypto_links",
        "crypto_link_withdrawals",
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
        # base neuve : packs « base » et « ch » (pays par défaut), plus de règles « seed- »
        assert dict(conn.execute(text("SELECT name, version FROM rule_packs")).fetchall()) == {
            "base": packs.available()["base"].version,
            "ch": packs.available()["ch"].version,
        }
        crypto = {
            r[0] for r in conn.execute(text("SELECT pattern FROM rules WHERE category_id='crypto'"))
        }
        assert {"swissborg", "kucoin", "bitpanda", "crypto.com", "pocket bitcoin"} <= crypto
        assert conn.execute(text("SELECT count(*) FROM rules WHERE id LIKE 'seed-%'")).scalar() == 0
        packed = conn.execute(text("SELECT count(*) FROM rules WHERE id LIKE 'pack-%'")).scalar()
        assert packed is not None
        assert packed > 200
        personal = conn.execute(
            text(
                "SELECT count(*) FROM categories "
                "WHERE id IN ('transfer-revolut', 'transfer-raiffeisen')"
            )
        ).scalar()
        assert personal == 0
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
                "amount_minor": 100,
                "cadence": "month",
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
    from hub.domains.finance.domain import MIGRATIONS
    from hub.platform import migrations as runner
    from tests.finance.conftest import finance_settings

    settings = finance_settings(tmp_path)
    domain = FinanceDomain(settings)
    runner.upgrade(MIGRATIONS, domain.path, "0001_ledger")
    ready_account(domain)
    runner.upgrade(MIGRATIONS, domain.path)
    assert domain.verify().ok
    domain.engine().dispose()


def test_double_sas_migration_keeps_the_month_start_and_the_debt_balances(
    tmp_path: Path,
) -> None:
    """0021 : le jour de début de mois devient une règle depuis toujours, les soldes constatés
    passent en ajout seul ; rien n'est effacé des anciennes tables."""
    from hub.domains.finance.domain import MIGRATIONS
    from hub.domains.finance.registre.model import period
    from hub.platform import migrations as runner
    from tests.finance.conftest import finance_settings

    settings = finance_settings(tmp_path)
    domain = FinanceDomain(settings)
    runner.upgrade(MIGRATIONS, domain.path, "0020_reconcile_decisions")
    engine = make_engine(domain.path)
    with begin_immediate(engine) as conn:
        conn.execute(
            text(
                "INSERT INTO budget_period (id, start_day, updated_at, actor) "
                "VALUES (1, 25, '2026-10-01T00:00:00.000Z', 'passkey:x')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO debts (id, name, lender, kind, currency, rate, created_at, "
                "updated_at) VALUES ('d1', 'Prêt', 'X', 'loan', 'CHF', '0', "
                "'2026-10-01T00:00:00.000Z', '2026-10-01T00:00:00.000Z')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO debt_balances (debt_id, on_date, amount_minor, source, created_at) "
                "VALUES ('d1', '2026-10-01', 500000, 'opening', '2026-10-01T00:00:00.000Z')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO accounts (id, institution, name, kind, currency, created_at) "
                "VALUES ('a1', 'Phantom', 'Phantom', 'crypto', 'CHF', '2026-10-01T00:00:00.000Z')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO reconcile_decisions (id, account_id, asset, break_kind, decision, "
                "on_date, quantity, currency, created_at, actor) VALUES ('r1', 'a1', "
                "'CRYPTO:BONK', 'no_price', 'accept', '2026-10-20', '1', 'CHF', "
                "'2026-10-20T00:00:00.000Z', 'x')"
            )
        )
    engine.dispose()
    runner.upgrade(MIGRATIONS, domain.path)
    with domain.engine().connect() as conn:
        # la table des décisions est rebâtie à l'identique, et accepte « change ancien »
        assert rows_of(
            conn, "SELECT id, break_kind, quantity, proposal_id FROM reconcile_decisions"
        ) == [("r1", "no_price", "1", None)]
    with begin_immediate(domain.engine()) as conn:
        conn.execute(
            text(
                "INSERT INTO reconcile_decisions (id, account_id, asset, break_kind, decision, "
                "on_date, currency, created_at, actor) VALUES ('r2', 'a1', 'USD', 'stale_fx', "
                "'accept', '2026-10-27', 'CHF', '2026-10-27T00:00:00.000Z', 'x')"
            )
        )
    with domain.engine().connect() as conn:
        assert rows_of(conn, "SELECT valid_from, start_day FROM budget_period_rules") == [
            ("1900-01", 25)
        ]
        assert rows_of(conn, "SELECT start_day FROM budget_period") == [(25,)]
        assert rows_of(
            conn, "SELECT id, debt_id, on_date, amount_minor FROM debt_balance_records"
        ) == [("legacy|d1|2026-10-01", "d1", "2026-10-01", 500000)]
        assert rows_of(conn, "SELECT count(*) FROM debt_balances") == [(1,)]
        assert period.start_day("2026-11") == 25
    domain.engine().dispose()


def rows_of(conn: object, sql: str) -> list[tuple[object, ...]]:
    from sqlalchemy import Connection

    assert isinstance(conn, Connection)
    return [tuple(r) for r in conn.execute(text(sql)).fetchall()]


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


def test_crypto_moves_migration_takes_the_legs_and_links_them_once(tmp_path: Path) -> None:
    """0022 : les jambes crypto quittent le détail `fx_json` pour `crypto_moves` ; l'autre côté
    relevé à l'import (`peer`), la marque de staking (`stake`) et les anciennes règles de lecture
    (fenêtre de quelques jours, claim dans les 60 jours) deviennent des liens écrits une fois,
    signés par la migration. Après elle, rien ne reste à proposer."""
    from hub.domains.finance.domain import MIGRATIONS
    from hub.domains.finance.patrimoine.app import crypto_moves, crypto_pairing
    from hub.platform import migrations as runner
    from tests.finance.conftest import finance_settings

    settings = finance_settings(tmp_path)
    domain = FinanceDomain(settings)
    runner.upgrade(MIGRATIONS, domain.path, "0021_double_sas")
    engine = make_engine(domain.path)
    at = "2026-10-01T00:00:00.000Z"
    entries = [
        # seq, compte, jour, code, montant, détail
        (
            "b",
            "2026-03-02",
            "EXCHANGE/TRADE/BUY",
            -100_000,
            {"currency": "BTC", "quantity": "0.02"},
        ),
        ("b", "2026-03-02", "EXCHANGE/DEPOSIT", 100_000, {"currency": "CHF", "quantity": "1000"}),
        (
            "b",
            "2026-04-01",
            "EXCHANGE/WITHDRAWAL",
            -50_000,
            {"currency": "BTC", "quantity": "-0.01", "txid": "t1"},
        ),
        (
            "l",
            "2026-04-01",
            "CRYPTO/RECEIVE",
            50_000,
            {"currency": "BTC", "quantity": "0.01", "txid": "t1", "peer": 3},
        ),
        ("l", "2026-08-01", "CRYPTO/SEND", -25_000, {"currency": "BTC", "quantity": "-0.005"}),
        (
            "l",
            "2026-09-01",
            "CRYPTO/RECEIVE",
            27_500,
            {"currency": "BTC", "quantity": "0.0055", "stake": True},
        ),
        (
            "b",
            "2026-10-01",
            "EXCHANGE/WITHDRAWAL",
            -20_000,
            {"currency": "BTC", "quantity": "-0.004"},
        ),
        ("l", "2026-10-02", "CRYPTO/RECEIVE", 19_500, {"currency": "BTC", "quantity": "0.0039"}),
        ("l", "2026-10-03", "CRYPTO/RECEIVE", 1_000, None),  # sans détail : pas une jambe
    ]
    with begin_immediate(engine) as conn:
        for acc, name in (("b", "Binance"), ("l", "Ledger")):
            conn.execute(
                text(
                    "INSERT INTO accounts (id, institution, name, kind, currency, created_at) "
                    "VALUES (:id, :n, :n, 'crypto', 'CHF', :at)"
                ),
                {"id": acc, "n": name, "at": at},
            )
        for i, (acc, on, code, amount, detail) in enumerate(entries, start=1):
            conn.execute(
                text(
                    "INSERT INTO entries (seq, id, account_id, kind, booking_date, amount_minor, "
                    "currency, bank_tx_code, fx_json, search_text, dedup_key, created_at, hash_v, "
                    "row_hash) VALUES (:seq, :id, :acc, 'movement', :on, :amount, 'CHF', :code, "
                    ":fx, '', :id, :at, 1, 'x')"
                ),
                {
                    "seq": i,
                    "id": f"e{i}",
                    "acc": acc,
                    "on": on,
                    "amount": amount,
                    "code": code,
                    "fx": None if detail is None else json.dumps(detail),
                    "at": at,
                },
            )
    engine.dispose()
    runner.upgrade(MIGRATIONS, domain.path)
    with domain.engine().connect() as conn:
        assert rows_of(
            conn, "SELECT entry_seq, role, asset, quantity, txid FROM crypto_moves ORDER BY 1"
        ) == [
            (1, "trade", "BTC", "0.02", None),
            (2, "in", "CHF", "1000", None),
            (3, "out", "BTC", "-0.01", "t1"),
            (4, "in", "BTC", "0.01", "t1"),
            (5, "out", "BTC", "-0.005", None),
            (6, "in", "BTC", "0.0055", None),
            (7, "out", "BTC", "-0.004", None),
            (8, "in", "BTC", "0.0039", None),
        ]
        assert rows_of(
            conn,
            "SELECT id, entry_seq, kind, peer_seq, method, actor FROM crypto_links ORDER BY id",
        ) == [
            ("legacy|claim|5", 5, "stake", 6, "claim", "migration:0022"),
            ("legacy|stake|6", 6, "stake", None, "source", "migration:0022"),
            ("legacy|transfer|4", 4, "transfer", 3, "quantity", "migration:0022"),
            ("legacy|window|8", 8, "transfer", 7, "window", "migration:0022"),
        ]
        found = crypto_moves.moves(conn, "2026-10-27")
        assert [(m.seq, m.role, m.internal) for m in found] == [
            (1, "trade", False),
            (3, "out", True),
            (4, "in", True),
            (5, "stake", True),
            (6, "stake", True),
            (7, "out", True),
            (8, "in", True),
        ]
        assert crypto_pairing.candidates(found) == []
        assert rows_of(conn, "SELECT count(*) FROM entries WHERE fx_json IS NOT NULL") == [(8,)]
    with (
        pytest.raises(DatabaseError, match=r"ledger\.append_only"),
        begin_immediate(domain.engine()) as conn,
    ):
        conn.execute(text("UPDATE crypto_links SET peer_seq = 1 WHERE id = 'legacy|window|8'"))
    domain.engine().dispose()


def test_budget_cadence_migration_keeps_old_targets_readable(tmp_path: Path) -> None:
    """0023 : une ancienne cible annuelle (un douzième arrondi, réglage `budget_cadence`) se
    relit telle quelle ; une nouvelle garde le montant saisi, exact."""
    from hub.domains.finance.classement.app import insights
    from hub.domains.finance.domain import MIGRATIONS
    from hub.platform import migrations as runner
    from tests.finance.conftest import finance_settings

    settings = finance_settings(tmp_path)
    domain = FinanceDomain(settings)
    runner.upgrade(MIGRATIONS, domain.path, "0022_crypto_moves")
    engine = make_engine(domain.path)
    at = "2026-10-01T00:00:00.000Z"
    with begin_immediate(engine) as conn:
        conn.execute(
            text(
                "INSERT INTO budgets (category_id, monthly_minor, currency, valid_from, "
                "created_at, hash_v) VALUES ('voyages', 8333, 'CHF', '2026-01-01', :at, 1)"
            ),
            {"at": at},
        )
        conn.execute(
            text(
                "INSERT INTO budget_cadence (category_id, cadence, updated_at, actor) "
                "VALUES ('voyages', 'year', :at, 'x')"
            ),
            {"at": at},
        )
    engine.dispose()
    runner.upgrade(MIGRATIONS, domain.path)
    with domain.engine().connect() as conn:
        old = insights.targets(conn, "2026-10")["voyages"]
        assert (old.amount, old.cadence, old.annual, old.monthly) == (99_996, "year", 99_996, 8333)
        assert insights.yearly(conn) == {"voyages"}
    with begin_immediate(domain.engine()) as conn:
        ledger.append(
            conn,
            "budgets",
            {
                "category_id": "voyages",
                "monthly_minor": 8333,
                "amount_minor": 100_000,
                "cadence": "year",
                "currency": "CHF",
                "valid_from": "2026-01-01",
                "proposal_id": None,
                "created_at": at,
            },
        )
    with domain.engine().connect() as conn:
        new = insights.targets(conn, "2026-10")["voyages"]
        assert (new.amount, new.cadence, new.annual, new.monthly) == (
            100_000,
            "year",
            100_000,
            8333,
        )
        assert rows_of(conn, "SELECT hash_v FROM budgets ORDER BY seq") == [(1,), (2,)]
    domain.engine().dispose()
