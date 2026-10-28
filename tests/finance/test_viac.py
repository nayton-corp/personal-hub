"""Lot 4 : parseurs VIAC, import des avis et rapports, reprise d'historique VIAC."""

from __future__ import annotations

import shutil
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from hub.core.db import begin_immediate
from hub.domains.finance import catalog, importer
from hub.domains.finance.domain import FinanceDomain
from hub.domains.finance.importer import Incoming
from hub.domains.finance.viac import ViacError
from hub.domains.finance.viac import notice as viac_notice
from hub.domains.finance.viac import report as viac_report
from hub.domains.finance.viac import text as viac_text
from hub.domains.finance.viac.apply import cash_ref, titles_ref
from tests.factories import viac as f
from tests.finance.conftest import rows

D1 = date(2026, 3, 2)
D2 = date(2026, 3, 5)
D3 = date(2026, 6, 30)


# --- parseurs --------------------------------------------------------------------------------


def test_parse_buy_and_sell() -> None:
    n = viac_notice.parse(f.buy(D2, "12.345", "1234.50", price="100.00"))
    assert (n.kind, n.portfolio, n.value_date) == ("buy", f.PORTFOLIO, "2026-03-05")
    assert (n.amount, n.quantity, n.isin) == (
        Decimal("1234.50"),
        Decimal("12.345"),
        f.FUND_WORLD[1],
    )
    assert n.fund == f.FUND_WORLD[0]
    assert n.is_trade
    s = viac_notice.parse(f.buy(D2, "2", "220.00", sell=True))
    assert s.kind == "sell"


@pytest.mark.parametrize(
    ("txt", "kind", "amount"),
    [
        (f.dividend(D3, "6.00"), "dividend", "6.00"),
        (f.interest(D3, "0.85"), "interest", "0.85"),
        (f.fee(D3, "11.20"), "fee", "11.20"),
        (f.deposit(D1, "7258.00"), "deposit", "7258.00"),
        (f.deposit(D1, "500.00", withdrawal=True), "withdrawal", "500.00"),
    ],
)
def test_parse_cash_notices(txt: str, kind: str, amount: str) -> None:
    n = viac_notice.parse(txt)
    assert (n.kind, n.amount, n.is_trade) == (kind, Decimal(amount), False)


def test_buy_printed_as_zero_parts_keeps_its_amount() -> None:
    # petit achat de rééquilibrage : VIAC imprime « 0.00 parts » pour 0.004 part
    n = viac_notice.parse(f.buy(D2, "0.00", "0.40", price="100.00"))
    assert (n.kind, n.amount, n.quantity) == ("buy", Decimal("0.40"), Decimal("0.004"))
    # en devise, l'avis ne donne pas le taux : le montant reste, sans parts
    usd = viac_notice.parse(f.buy(D2, "0.00", "0.40", price="100.00", currency="USD"))
    assert (usd.kind, usd.amount, usd.quantity) == ("buy", Decimal("0.40"), None)


def test_zero_parts_buy_in_foreign_currency_moves_cash_only(viac: FinanceDomain) -> None:
    open_portfolio(viac)
    txt = f.buy(D2, "0.00", "0.40", price="100.00", currency="USD")
    report = viac.importer.process([Incoming("b.pdf", f.fake_pdf(txt))])
    assert {s.status for s in report.statements} == {"applied"}
    amounts = rows(viac, "SELECT amount_minor FROM entries WHERE kind = 'movement' ORDER BY 1")
    assert amounts == [(-40,), (40,)]
    assert rows(viac, "SELECT count(*) FROM trades") == [(0,)]


def test_nil_fee_is_recognized_not_refused() -> None:
    txt = f.fee(D3, "0.00")
    assert viac_notice.classify(txt) == "nil_fee"
    assert viac_notice.ignored(txt) is not None
    assert viac_notice.classify(f.fee(D3, "11.20")) == "notice"


def test_attestation_is_recognized_not_a_deposit() -> None:
    txt = f.attestation(2025, "7258.00")
    assert viac_notice.classify(txt) == "attestation"
    assert viac_notice.ignored(txt) is not None


def test_unknown_notice_is_refused() -> None:
    with pytest.raises(ViacError, match="type d'avis inconnu"):
        viac_notice.parse(f._letter("Lettre d'information", f.PORTFOLIO, D1, ["Bonjour."]))
    with pytest.raises(ViacError):
        viac_notice.parse("Versement\nrien d'autre")


def test_parse_report() -> None:
    txt = f.report(
        D3,
        [
            f.Folio(
                "VIAC1",
                cash="120.50",
                positions=[
                    f.Pos("12.345", "1358.00"),
                    f.Pos("3", "330.00", f.FUND_RE, "Immobilier Suisse", "Immobilier"),
                ],
            ),
            f.Folio("VIAC2", f.PORTFOLIO_2, positions=[f.Pos("1", "110.00", f.FUND_CH)]),
        ],
    )
    assert viac_notice.classify(txt) == "report"
    r = viac_report.parse(txt)
    assert r.on_date == "2026-06-30"
    one, two = r.portfolios
    assert (one.number, one.name, one.cash) == (f.PORTFOLIO, "VIAC1", Decimal("120.50"))
    assert [(p.isin, p.quantity, p.value, p.category) for p in one.positions] == [
        (f.FUND_WORLD[1], Decimal("12.345"), Decimal("1358.00"), "Actions"),
        (f.FUND_RE[1], Decimal("3"), Decimal("330.00"), "Immobilier"),
    ]
    assert one.balance == Decimal("1808.50")
    assert (two.number, two.cash, len(two.positions)) == (f.PORTFOLIO_2, None, 1)


def test_report_without_portfolio_is_refused() -> None:
    with pytest.raises(ViacError):
        viac_report.parse("Rapport au 30.06.2026\nRécapitulation\n")


@pytest.mark.skipif(shutil.which("pdftotext") is None, reason="poppler-utils absent")
def test_real_pdf_through_pdftotext() -> None:
    txt = f.report(D3, [f.Folio("VIAC1", cash="120.50", positions=[f.Pos("12.345", "1358.00")])])
    out = viac_text.pdftotext(f.real_pdf(txt))
    r = viac_report.parse(out)
    assert r.portfolios[0].positions[0].quantity == Decimal("12.345")
    n = viac_notice.parse(viac_text.pdftotext(f.real_pdf(f.buy(D2, "1.5", "150.00"))))
    assert (n.kind, n.amount) == ("buy", Decimal("150.00"))


def test_pdftotext_refuses_non_pdf() -> None:
    with pytest.raises(ViacError, match="pas un PDF"):
        viac_text.pdftotext(b"<xml/>")


# --- import ----------------------------------------------------------------------------------


@pytest.fixture
def viac(finance: FinanceDomain) -> FinanceDomain:
    finance.importer.pdf_text = f.fake_text
    return finance


def add_portfolio(domain: FinanceDomain, number: str = f.PORTFOLIO) -> tuple[str, str]:
    with begin_immediate(domain.engine()) as conn:
        ids = tuple(
            catalog.add_account(
                conn,
                institution="VIAC",
                name=f"VIAC {side}",
                kind="pension",
                external_ref=ref,
            ).id
            for side, ref in (("cash", cash_ref(number)), ("titres", titles_ref(number)))
        )
    return ids  # type: ignore[return-value]


def open_portfolio(domain: FinanceDomain, number: str = f.PORTFOLIO) -> tuple[str, str]:
    cash, titles = add_portfolio(domain, number)
    with begin_immediate(domain.engine()) as conn:
        for a in (cash, titles):
            importer.open_account(conn, a, "2026-01-01", 0, "CHF")
    return cash, titles


def send(domain: FinanceDomain, *docs: str) -> importer.BatchReport:
    return domain.importer.process(
        [Incoming(f"doc{i}.pdf", f.fake_pdf(t)) for i, t in enumerate(docs)]
    )


def balance(domain: FinanceDomain, account_id: str) -> int:
    ((v,),) = rows(
        domain,
        "SELECT coalesce(sum(amount_minor), 0) FROM entries WHERE account_id = :a",
        a=account_id,
    )
    return int(v)  # type: ignore[call-overload]


def test_buy_moves_cash_to_titles(viac: FinanceDomain) -> None:
    cash, titles = open_portfolio(viac)
    report = send(viac, f.deposit(D1, "1000.00"), f.buy(D2, "9.5", "950.00"))
    assert report.counters()["new_entries"] == 3
    assert (balance(viac, cash), balance(viac, titles)) == (5000, 95000)
    cats = rows(
        viac,
        "SELECT e.bank_tx_code, c.category_id FROM entries e JOIN categorizations c "
        "ON c.entry_seq = e.seq WHERE e.kind = 'movement' ORDER BY e.seq",
    )
    assert cats == [
        ("VIAC/DEPOSIT", "transfer-own"),
        ("VIAC/TRADE/BUY", "transfer-titres"),
        ("VIAC/TRADE/BUY", "transfer-titres"),
    ]
    assert rows(viac, "SELECT isin, quantity, amount_minor FROM trades") == [
        (f.FUND_WORLD[1], "9.5", 95000)
    ]
    assert rows(viac, "SELECT price, source FROM prices") == [("100", "viac_notice")]
    assert viac.verify_ledger().ok


def test_notice_price_is_the_printed_chf_price(viac: FinanceDomain) -> None:
    # 4.00 CHF pour « 0.03 part » à 120 : les parts arrondies donneraient 133.33
    open_portfolio(viac)
    send(viac, f.buy(D2, "0.03", "4.00", price="120.00"))
    assert rows(viac, "SELECT price FROM prices WHERE source = 'viac_notice'") == [("120",)]


def test_income_and_fees_are_categorized(viac: FinanceDomain) -> None:
    cash, _ = open_portfolio(viac)
    send(viac, f.dividend(D3, "6.00"), f.interest(D3, "0.85"), f.fee(D3, "11.20"))
    assert balance(viac, cash) == 600 + 85 - 1120
    cats = rows(
        viac,
        "SELECT c.category_id FROM entries e JOIN categorizations c ON c.entry_seq = e.seq "
        "ORDER BY c.category_id",
    )
    assert cats == [("frais-placement",), ("rendement",), ("rendement",)]


def test_same_notice_twice_is_a_duplicate(viac: FinanceDomain) -> None:
    open_portfolio(viac)
    send(viac, f.deposit(D1, "1000.00"))
    again = f.deposit(D1, "1000.00") + "\nCopie\n"  # autre fichier, même opération
    report = send(viac, again)
    assert report.counters()["new_entries"] == 0
    assert report.counters()["duplicate_entries"] == 1


def test_unknown_portfolio_waits_then_replays(viac: FinanceDomain) -> None:
    report = send(viac, f.deposit(D1, "1000.00"))
    assert report.statements[0].reasons == ["unknown_account"]
    assert rows(viac, "SELECT status FROM imports") == [("needs_review",)]
    open_portfolio(viac)
    replay = viac.importer.retry_needs_review()
    assert [o.status for o in replay] == ["applied"]
    assert rows(viac, "SELECT status FROM imports") == [("applied",)]


def test_no_opening_waits(viac: FinanceDomain) -> None:
    add_portfolio(viac)
    report = send(viac, f.buy(D2, "1", "100.00"))
    assert report.statements[0].reasons == ["no_opening"]
    # aucune carte apply_import : il faut d'abord ouvrir le compte
    assert rows(viac, "SELECT count(*) FROM events WHERE type = 'proposal.request'") == [(0,)]


def test_attestation_and_garbage(viac: FinanceDomain) -> None:
    open_portfolio(viac)
    report = viac.importer.process(
        [
            Incoming("att.pdf", f.fake_pdf(f.attestation(2025, "7258.00"))),
            Incoming("fee.pdf", f.fake_pdf(f.fee(D3, "0.00"))),
            Incoming("x.pdf", b"%PDF-1.4\nautre chose"),
        ]
    )
    assert [(o.status, o.reason) for o in report.files] == [
        ("ignored", "viac.attestation"),
        ("ignored", "viac.nil_fee"),
        ("rejected", "viac.unreadable"),
    ]
    assert rows(viac, "SELECT count(*) FROM entries WHERE kind = 'movement'") == [(0,)]


def test_report_records_holdings_and_checks(viac: FinanceDomain) -> None:
    cash, titles = open_portfolio(viac)
    send(viac, f.deposit(D1, "1000.00"), f.buy(D2, "9.5", "950.00"))
    folio = f.Folio("VIAC1", cash="50.00", positions=[f.Pos("9.5", "1045.00")])
    report = send(viac, f.report(D3, [folio]))
    assert [o.status for o in report.statements] == ["applied", "applied"]
    assert all(o.reasons == [] for o in report.statements)
    assert rows(viac, "SELECT account_id, quantity, value_minor FROM holdings") == [
        (titles, "9.5", 104500)
    ]
    assert rows(viac, "SELECT price FROM prices WHERE source = 'viac_report'") == [("110",)]
    assert rows(viac, "SELECT account_id, amount_minor FROM checkpoints") == [(cash, 5000)]


def test_report_flags_differences_without_blocking(viac: FinanceDomain) -> None:
    open_portfolio(viac)
    send(viac, f.buy(D2, "9.5", "950.00"))
    folio = f.Folio("VIAC1", cash="80.00", positions=[f.Pos("10", "1100.00")])
    report = send(viac, f.report(D3, [folio]))
    assert {o.status for o in report.statements} == {"applied"}
    assert set(report.statements[0].reasons) == {"holdings_mismatch", "ledger_check_failed"}
    assert rows(viac, "SELECT status FROM imports ORDER BY received_at DESC LIMIT 1") == [
        ("applied",)
    ]


def test_same_day_order_deposit_before_buy(viac: FinanceDomain) -> None:
    open_portfolio(viac)
    # le rapport et l'achat arrivent avant le versement dans le lot : l'ordre des dates gagne
    folio = f.Folio("VIAC1", cash="50.00", positions=[f.Pos("9.5", "1045.00")])
    report = send(viac, f.report(D2, [folio]), f.buy(D2, "9.5", "950.00"), f.deposit(D2, "1000.00"))
    assert all(o.reasons == [] for o in report.statements)


def test_viac_history(viac: FinanceDomain, tmp_path: Path) -> None:
    add_portfolio(viac)
    folder = tmp_path / "viac-history"
    (folder / "2026").mkdir(parents=True)
    docs = {
        "2026/a.pdf": f.deposit(D1, "1000.00"),
        "2026/b.pdf": f.buy(D2, "9.5", "950.00"),
        "c.pdf": f.report(D3, [f.Folio("VIAC1", cash="50.00", positions=[f.Pos("9.5", "1045")])]),
        "d.pdf": f.attestation(2025, "7258.00"),
        "e.pdf": f.fee(D2, "0.00"),
    }
    for name, txt in docs.items():
        (folder / name).write_bytes(f.fake_pdf(txt))
    report = importer.import_viac_history(viac.importer, folder)
    assert report.ok, report.public()
    assert report.warnings == []
    (acc,) = report.accounts
    assert acc == {
        "account": f.PORTFOLIO,
        "entries": 3,
        "from": "2026-03-02",
        "to": "2026-03-05",
        "reports": 1,
    }
    openings = rows(viac, "SELECT booking_date, amount_minor FROM entries WHERE kind = 'opening'")
    assert openings == [("2026-03-01", 0), ("2026-03-01", 0)]
    # une deuxième reprise ne trouve rien de nouveau et n'écrit rien
    again = importer.import_viac_history(viac.importer, folder)
    assert again.ok
    assert again.batch["files"] == 0


def test_viac_history_refuses_unknown_portfolio(viac: FinanceDomain, tmp_path: Path) -> None:
    (tmp_path / "a.pdf").write_bytes(f.fake_pdf(f.deposit(D1, "1000.00")))
    report = importer.import_viac_history(viac.importer, tmp_path)
    assert not report.ok
    assert report.error is not None
    assert "add-portfolio" in report.error
    assert rows(viac, "SELECT count(*) FROM imports") == [(0,)]


def test_viac_history_refuses_unreadable(viac: FinanceDomain, tmp_path: Path) -> None:
    add_portfolio(viac)
    (tmp_path / "a.pdf").write_bytes(f.fake_pdf("Lettre quelconque\nPortefeuille 3.100.200.300.01"))
    report = importer.import_viac_history(viac.importer, tmp_path)
    assert not report.ok
    assert report.error is not None
    assert report.error.startswith("viac.unrecognized")
    assert rows(viac, "SELECT count(*) FROM entries") == [(0,)]


# --- valorisation ----------------------------------------------------------------------------


def test_titles_are_valued_by_positions(viac: FinanceDomain) -> None:
    from hub.domains.finance import insights, valuation

    open_portfolio(viac)
    send(viac, f.deposit(D1, "1000.00"), f.buy(D2, "9.5", "950.00"))
    with viac.engine().connect() as conn:
        v = valuation.value_at(conn, "2026-03-31")
    # avant tout rapport : parts des avis au cours de l'achat
    assert (v.net_worth, v.deposits, v.by_envelope["pilier3a"]) == (100000, 100000, 100000)
    folio = f.Folio("VIAC1", cash="56.00", positions=[f.Pos("9.5", "1045.00")])
    send(viac, f.dividend(D3, "6.00"), f.report(D3, [folio]))
    with viac.engine().connect() as conn:
        v = valuation.value_at(conn, D3.isoformat())
        later = valuation.value_at(conn, "2026-07-15")
        (s,) = valuation.series(conn, [D3.isoformat()])
        h = insights.holdings(conn, D3.isoformat())
    # valeur : 56 de liquidités + 1045 de titres ; versements : 1000 ; marché : 101 (dividende
    # compris)
    assert (v.net_worth, v.deposits) == (110100, 100000)
    assert (s.net_worth, s.deposits) == (v.net_worth, v.deposits)
    assert later.net_worth == v.net_worth
    (item,) = h["items"]
    assert (item["isin"], item["quantity"], item["price"]) == (f.FUND_WORLD[1], "9.5", "110")
    assert (item["value"]["minor"], item["cost"]["minor"], item["gain"]["minor"]) == (
        104500,
        95000,
        9500,
    )
    assert item["weight"] == "1.0000"
    assert item["name"] == f.FUND_WORLD[0]
    assert h["missing_prices"] == []


def test_trade_after_report_moves_quantities(viac: FinanceDomain) -> None:
    from hub.domains.finance import valuation

    _, titles = open_portfolio(viac)
    send(viac, f.deposit(D1, "2000.00"), f.buy(D2, "9.5", "950.00"))
    send(viac, f.report(D3, [f.Folio("VIAC1", cash="1050.00", positions=[f.Pos("9.5", "1045")])]))
    send(viac, f.buy(date(2026, 7, 2), "5", "600.00", price="120.00"))
    with viac.engine().connect() as conn:
        p = valuation.Positions(conn)
        (line,) = p.lines(titles, "2026-07-31")
    assert (line.quantity, line.price, line.value) == (Decimal("14.5"), Decimal(120), 174000)


def test_pillar3a_counts_viac_deposits(viac: FinanceDomain) -> None:
    from hub.domains.finance import insights

    open_portfolio(viac)
    send(viac, f.deposit(D1, "3000.00"), f.deposit(D2, "500.00", withdrawal=True))
    with viac.engine().connect() as conn:
        p = insights.pillar3a(conn, 2026, date(2026, 10, 27))
    assert (p["paid"]["minor"], p["source"]) == (300000, "viac")
    assert p["margin"]["minor"] == 725800 - 300000


def test_accounts_route_gives_market_value(viac: FinanceDomain) -> None:
    from hub.domains.finance import reads

    _, titles = open_portfolio(viac)
    send(viac, f.deposit(D1, "1000.00"), f.buy(D2, "9.5", "950.00"))
    send(viac, f.report(D3, [f.Folio("VIAC1", cash="50.00", positions=[f.Pos("9.5", "1045")])]))
    with viac.engine().connect() as conn:
        by_id = {a["id"]: a for a in reads.accounts(conn)}
    assert by_id[titles]["balance"]["minor"] == 95000
    assert by_id[titles]["value"]["minor"] == 104500
