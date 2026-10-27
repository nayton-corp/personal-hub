"""Lot 6 : relevés IBKR (Flex Query), comptes par devise, positions, valorisation en CHF."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from hub.core.db import begin_immediate
from hub.domains.finance import catalog, ibkr, importer, valuation
from hub.domains.finance.domain import FinanceDomain
from hub.domains.finance.importer import Incoming
from tests.factories import ibkr as f
from tests.finance.conftest import rows

START, END = date(2026, 1, 1), date(2026, 3, 31)


def add_ibkr(finance: FinanceDomain) -> catalog.Account:
    with begin_immediate(finance.engine()) as conn:
        return catalog.add_account(
            conn,
            institution="IBKR",
            name="IBKR titres",
            kind="securities",
            external_ref=ibkr.titles_ref(f.ACCOUNT),
        )


def quarter() -> f.Flex:
    return f.Flex(
        START,
        END,
        cash=[("CHF", "0", "5998.00"), ("USD", "0", "1711.75")],
        positions=[f.position(f.VT, "30", "120", "3600")],
        trades=[
            f.fx_trade("901", date(2026, 1, 6), "USD.CHF", "5000", "0.80", "-4000"),
            f.buy("902", date(2026, 1, 7), f.VT, "30", "110", "-3300"),
        ],
        cash_txs=[
            f.cash_tx("801", date(2026, 1, 5), "Deposits/Withdrawals", "10000"),
            f.cash_tx("802", date(2026, 3, 20), "Dividends", "15", "USD"),
            f.cash_tx("803", date(2026, 3, 20), "Withholding Tax", "-2.25", "USD"),
        ],
        rates=[("USD", "0.79")],
    )


def test_parse_flex() -> None:
    pf = ibkr.parse(f.flex(quarter()))
    (st,) = pf.statements
    assert (st.account, st.base_currency, st.from_date, st.to_date) == (
        f.ACCOUNT,
        "CHF",
        "2026-01-01",
        "2026-03-31",
    )
    assert st.currencies == {"CHF", "USD"}
    assert [c.currency for c in st.cash] == ["CHF", "USD"]  # BASE_SUMMARY laissé de côté
    assert st.positions is not None
    assert st.positions[0].key == f.VT[0]
    assert [t.category for t in st.trades] == ["CASH", "STK"]
    assert [c.code for c in st.cash_txs] == [
        "IBKR/DEPOSIT",
        "IBKR/INCOME/DIVIDEND",
        "IBKR/INCOME/TAX",
    ]
    assert ibkr.is_flex(f.flex(quarter()))
    assert not ibkr.is_flex(b"<Document/>")


def test_dates_and_refusals() -> None:
    assert ibkr.iso_date("20261027;093000") == "2026-10-27"
    assert ibkr.iso_date("2026-10-27, 09:30:00") == "2026-10-27"
    assert ibkr.iso_date("10/27/2026") == "2026-10-27"
    with pytest.raises(ibkr.FlexError):
        ibkr.iso_date("27 oct.")
    with pytest.raises(ibkr.FlexError):
        ibkr.parse(b"<FlexQueryResponse><FlexStatements/></FlexQueryResponse>")
    entity = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><FlexQueryResponse/>'
    assert not ibkr.is_flex(entity)


def test_import_creates_currency_accounts_and_values_in_chf(finance: FinanceDomain) -> None:
    titles = add_ibkr(finance)
    report = finance.importer.process([Incoming("flex.xml", f.flex(quarter()))])
    assert report.counters()["applied"] == 1
    assert [s.reasons for s in report.statements] == [[]]  # soldes de fin retrouvés
    refs = {r[0] for r in rows(finance, "SELECT external_ref FROM accounts")}
    assert {ibkr.cash_ref(f.ACCOUNT, "CHF"), ibkr.cash_ref(f.ACCOUNT, "USD")} <= refs
    # ouverture à zéro la veille du relevé, pour les trois comptes
    openings = rows(finance, "SELECT booking_date, amount_minor FROM entries WHERE kind='opening'")
    assert openings == [("2025-12-31", 0)] * 3
    codes = rows(
        finance,
        "SELECT e.bank_tx_code, e.amount_minor, e.currency, vc.category_id FROM entries e "
        "LEFT JOIN v_entry_category vc ON vc.entry_seq = e.seq WHERE e.kind = 'movement' "
        "ORDER BY e.seq",
    )
    assert codes == [
        ("IBKR/FX", 500_000, "USD", "transfer-own"),
        ("IBKR/FX", -400_000, "CHF", "transfer-own"),
        ("IBKR/FEE/COMMISSION", -200, "CHF", "frais-placement"),
        ("IBKR/TRADE/BUY", -330_000, "USD", "transfer-titres"),
        ("IBKR/TRADE/BUY", 264_000, "CHF", "transfer-titres"),
        ("IBKR/FEE/COMMISSION", -100, "USD", "frais-placement"),
        ("IBKR/DEPOSIT", 1_000_000, "CHF", "transfer-own"),
        ("IBKR/INCOME/DIVIDEND", 1500, "USD", "rendement"),
        ("IBKR/INCOME/TAX", -225, "USD", "rendement"),
    ]
    assert rows(finance, "SELECT isin, quantity, amount_minor, currency FROM trades") == [
        (f.VT[0], "30", 264_000, "CHF")
    ]
    assert rows(finance, "SELECT on_date, isin, quantity, value_minor, currency FROM holdings") == [
        ("2026-03-31", f.VT[0], "30", 360_000, "USD")
    ]
    assert rows(finance, "SELECT base, quote, rate, source FROM fx_rates") == [
        ("USD", "CHF", "0.79", "ibkr")
    ]
    assert rows(finance, "SELECT kind, symbol, currency FROM instruments") == [
        ("stock", "VT", "USD")
    ]
    with finance.engine().connect() as conn:
        v = valuation.value_at(conn, "2026-03-31")
    # 5998 CHF + 1711.75 USD × 0.79 + 30 VT × 120 USD × 0.79
    assert v.by_envelope["titres"] == 599_800 + 135_228 + 284_400
    assert v.net_worth == v.by_envelope["titres"]
    assert v.deposits == 1_000_000  # le versement seul : change, achats, frais, dividende exclus
    assert v.missing_fx == []
    assert v.missing_prices == []
    with finance.engine().connect() as conn:
        assert (
            valuation.account_value(valuation.Positions(conn), titles.id, 0, "2026-03-31")[0]
            == 284_400
        )
    assert finance.verify_ledger().ok


def test_overlapping_statement_is_deduplicated(finance: FinanceDomain) -> None:
    add_ibkr(finance)
    finance.importer.process([Incoming("q1.xml", f.flex(quarter()))])
    later = f.Flex(
        date(2026, 3, 15),
        date(2026, 4, 2),
        cash=[("USD", "1711.75", "1726.75")],
        positions=[f.position(f.VT, "30", "125", "3750")],
        cash_txs=[
            f.cash_tx("802", date(2026, 3, 20), "Dividends", "15", "USD"),
            f.cash_tx("803", date(2026, 3, 20), "Withholding Tax", "-2.25", "USD"),
            f.cash_tx("804", date(2026, 4, 1), "Broker Interest Received", "15", "USD"),
        ],
        rates=[("USD", "0.80")],
    )
    report = finance.importer.process([Incoming("daily.xml", f.flex(later))])
    (st,) = report.statements
    assert (st.status, st.new, st.duplicates) == ("applied", 2, 2)  # intérêt + positions
    assert st.reasons == []
    with finance.engine().connect() as conn:
        v = valuation.value_at(conn, "2026-04-02")
    assert v.by_envelope["titres"] == 599_800 + 138_140 + 300_000


def test_unknown_account_waits_then_applies(finance: FinanceDomain) -> None:
    report = finance.importer.process([Incoming("flex.xml", f.flex(quarter()))])
    assert report.statements[0].reasons == ["unknown_account"]
    assert rows(finance, "SELECT count(*) FROM entries") == [(0,)]
    add_ibkr(finance)
    retried = finance.importer.retry_needs_review()
    assert [o.status for o in retried] == ["applied"]


def test_entry_before_opening_rolls_back_the_statement(finance: FinanceDomain) -> None:
    add_ibkr(finance)
    finance.importer.process([Incoming("q1.xml", f.flex(quarter()))])
    older = f.Flex(
        date(2025, 12, 1),
        date(2025, 12, 31),
        cash=[("CHF", "0", "50")],
        cash_txs=[f.cash_tx("700", date(2025, 12, 10), "Deposits/Withdrawals", "50")],
    )
    report = finance.importer.process([Incoming("old.xml", f.flex(older))])
    assert report.statements[0].status == "needs_review"
    assert report.statements[0].reasons == ["before_opening"]
    assert rows(finance, "SELECT count(*) FROM checkpoints WHERE on_date = '2025-12-31'") == [(0,)]


def test_ledger_gap_is_reported_not_blocking(finance: FinanceDomain) -> None:
    add_ibkr(finance)
    st = quarter()
    st.cash = [("CHF", "0", "6000.00"), ("USD", "0", "1711.75")]
    report = finance.importer.process([Incoming("flex.xml", f.flex(st))])
    assert report.statements[0].status == "applied"
    assert report.statements[0].reasons == ["ledger_check_failed"]


def test_history_import(finance: FinanceDomain, tmp_path: Path) -> None:
    folder = tmp_path / "ibkr"
    (folder / "2026").mkdir(parents=True)
    (folder / "2026" / "q1.xml").write_bytes(f.flex(quarter()))
    first = f.Flex(
        date(2025, 10, 1),
        date(2025, 12, 31),
        cash=[("CHF", "200", "200")],
    )
    (folder / "q4.xml").write_bytes(f.flex(first))
    refused = importer.import_ibkr_history(finance.importer, folder)
    assert not refused.ok
    assert "compte IBKR inconnu" in str(refused.error)
    add_ibkr(finance)
    report = importer.import_ibkr_history(finance.importer, folder)
    assert report.ok, report.public()
    assert report.accounts == [
        {"account": f.ACCOUNT, "entries": 9, "from": "2025-10-01", "to": "2026-03-31"}
    ]
    # le plus ancien relevé ouvre le compte CHF au solde de départ d'IBKR
    assert rows(
        finance,
        "SELECT e.booking_date, e.amount_minor FROM entries e JOIN accounts a ON a.id = "
        "e.account_id WHERE e.kind = 'opening' AND a.external_ref = :r",
        r=ibkr.cash_ref(f.ACCOUNT, "CHF"),
    ) == [("2025-09-30", 20_000)]
    again = importer.import_ibkr_history(finance.importer, folder)
    assert not again.ok  # rien de nouveau
