"""Soldes crypto relevés plusieurs fois le même jour (migration 0019) : « Actualiser » met à jour
le patrimoine tout de suite, sans réécrire le relevé du matin (registre en ajout seul)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import text

from hub.domains.finance.domain import FinanceDomain
from hub.domains.finance.patrimoine.app import holdings, valuation
from hub.domains.finance.registre.app import catalog, ledger
from hub.domains.finance.sources.infra import market_file
from hub.domains.finance.sources.infra.files import Incoming
from hub.platform.db import begin_immediate
from tests.finance.conftest import finance_settings, ready_account, rows

DAY = "2026-10-31"


def _doc(name: str, balances: list[tuple[str, str]], **kw: object) -> Incoming:
    doc = {
        "format": market_file.FORMAT,
        "fetched_at": f"{DAY}T15:50:00Z",
        "balances": [
            {"account": "crypto:wallet", "instrument": i, "on_date": DAY, "quantity": q}
            for i, q in balances
        ],
        **kw,
    }
    return Incoming(name, json.dumps(doc).encode())


def _prices() -> list[dict[str, str]]:
    base = {"kind": "crypto", "on_date": DAY, "currency": "CHF", "source": "coingecko"}
    return [
        {**base, "instrument": "ETH", "price": "3000"},
        {**base, "instrument": "SOL", "price": "100"},
    ]


def _crypto(finance: FinanceDomain) -> int:
    with finance.engine().connect() as conn:
        return valuation.value_at(conn, DAY).by_envelope["crypto"]


def test_refresh_replaces_the_balance_of_the_day(finance: FinanceDomain) -> None:
    with begin_immediate(finance.engine()) as conn:
        catalog.add_account(
            conn, institution="Test", name="Wallet", kind="crypto",
            external_ref="crypto:wallet", currency="CHF",
        )  # fmt: skip
    morning = _doc("m1.json", [("ETH", "0.2"), ("SOL", "1")], prices=_prices())
    finance.importer.process([morning])
    assert _crypto(finance) == 70_000  # 0,2 × 3000 + 1 × 100

    # l'après-midi, un claim de staking : +0,53 ETH ; le SOL est parti
    finance.importer.process([_doc("m2.json", [("ETH", "0.73")])])
    assert _crypto(finance) == 219_000
    assert rows(finance, "SELECT isin, quantity FROM holdings ORDER BY seq") == [
        ("CRYPTO:ETH", "0.2"),
        ("CRYPTO:SOL", "1"),
        ("CRYPTO:ETH", "0.73"),
        ("CRYPTO:SOL", "0"),
    ]
    with finance.engine().connect() as conn:
        lines = holdings.holdings(conn, DAY)["items"]
    assert [(x["isin"], x["quantity"]) for x in lines] == [("CRYPTO:ETH", "0.73")]

    # même solde au passage suivant : rien de neuf
    finance.importer.process([_doc("m3.json", [("ETH", "0.73")])])
    assert rows(finance, "SELECT count(*) FROM holdings") == [(4,)]
    assert finance.verify().ok


def test_a_report_of_the_same_day_is_still_written_once(finance: FinanceDomain) -> None:
    """Hors soldes crypto (rapport VIAC, IBKR, saisie) : le premier relevé du jour reste."""
    from decimal import Decimal

    from hub.domains.finance.patrimoine.app import assets

    account = ready_account(finance)
    with begin_immediate(finance.engine()) as conn:
        conn.execute(
            text(
                "INSERT INTO imports (id, source, file_sha256, file_name, received_at, status, "
                "updated_at) VALUES ('i1', 'manual', 'h', 'f', :at, 'applied', :at)"
            ),
            {"at": f"{DAY}T10:00:00Z"},
        )
        args = (conn, account.id, DAY, "SYM:VT")
        assert assets.add_holding(*args, Decimal(2), Decimal(200), "CHF", "i1")
        assert not assets.add_holding(*args, Decimal(3), Decimal(300), "CHF", "i1")


@pytest.mark.migrations
def test_migration_keeps_rows_and_allows_a_second_report(tmp_path: Path) -> None:
    from hub.domains.finance.domain import MIGRATIONS
    from hub.platform import migrations as runner

    domain = FinanceDomain(finance_settings(tmp_path))
    runner.upgrade(MIGRATIONS, domain.path, "0018_account_target")
    account = ready_account(domain)
    row = {
        "account_id": account.id,
        "on_date": DAY,
        "isin": "CRYPTO:ETH",
        "quantity": "0.2",
        "value_minor": 60_000,
        "currency": "CHF",
        "cost_price": None,
        "import_id": "i1",
        "created_at": f"{DAY}T06:15:00Z",
    }
    with begin_immediate(domain.engine()) as conn:
        conn.execute(
            text(
                "INSERT INTO imports (id, source, file_sha256, file_name, received_at, status, "
                "updated_at) VALUES ('i1', 'market', 'h', 'f', :at, 'applied', :at)"
            ),
            {"at": f"{DAY}T06:15:00Z"},
        )
        seq = ledger.append(conn, "holdings", row)
    domain.engine().dispose()
    runner.upgrade(MIGRATIONS, domain.path)
    assert domain.is_current()
    assert domain.verify().ok
    with begin_immediate(domain.engine()) as conn:
        ledger.append(conn, "holdings", {**row, "quantity": "0.73", "value_minor": 219_000})
    assert rows(domain, "SELECT seq, quantity FROM holdings ORDER BY seq") == [
        (seq, "0.2"),
        (seq + 1, "0.73"),
    ]
    with domain.engine().connect() as conn, pytest.raises(Exception, match="append_only"):
        conn.execute(text("DELETE FROM holdings"))
    assert domain.verify().ok
    domain.engine().dispose()
