"""Lot 2 : instantanés (L2-01) et routes de l'app (L2-02), sur onze mois de relevés fictifs."""

from __future__ import annotations

import csv
import io
from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from hub.api.app import create_app
from hub.core.context import HubContext
from hub.core.db import begin_immediate
from hub.core.registry import Registry
from hub.domains.finance import catalog, importer, insights, ledger, snapshots, valuation
from hub.domains.finance.domain import FinanceDomain
from hub.domains.finance.importer import Incoming
from tests.factories.camt import IBAN, IBAN_2, OTHER_IBAN, Stmt, Tx, camt053
from tests.finance.conftest import finance_settings, rows
from tests.finance.test_finance_api import app_session, token

TODAY = date(2026, 10, 27)
MONTHS = ["2025-12", *[f"2026-{m:02d}" for m in range(1, 11)]]
RULE_OF = {
    "Employeur Fictif SA": "salaire",
    "Régie Fictive": "logement",
    "Épicerie du Coin": "alimentation",
    "Bistrot Fictif": "restaurants",
    "Fondation 3a Fictive": "epargne-3a",
}


def month_txs(month: str) -> list[Tx]:
    y, m = (int(x) for x in month.split("-"))

    def d(day: int) -> date:
        return date(y, m, day)

    txs = [
        Tx("1500.00", True, d(1), counterparty="Régie Fictive", label="Loyer"),
        Tx("100.00", True, d(5), counterparty="Épicerie du Coin"),
        Tx("100.00", True, d(12), counterparty="Épicerie du Coin"),
        Tx("100.00", True, d(19), counterparty="Épicerie du Coin"),
        Tx("80.00", True, d(14), counterparty="Bistrot Fictif"),
        Tx(
            "600.00", True, d(20), counterparty="Fondation 3a Fictive", counterparty_iban=OTHER_IBAN
        ),
        Tx("5000.00", False, d(25), counterparty="Employeur Fictif SA", label="Salaire"),
    ]
    if month == "2026-10":
        txs += [
            Tx("50.00", True, d(22), counterparty="Kiosque Inconnu"),
            Tx("20.00", False, d(23), counterparty="Remboursement Inconnu"),
        ]
    return txs


def statements(skip: set[str] | None = None) -> list[tuple[str, bytes]]:
    out = []
    balance = Decimal("1000.00")
    for month in MONTHS:
        y, m = (int(x) for x in month.split("-"))
        st = Stmt(balance, date(y, m, 1), month_txs(month), stmt_id=f"STMT-{month}")
        balance = st.computed_closing()
        if not skip or month not in skip:
            out.append((month, camt053(st)))
    return out


def categorize(fin: FinanceDomain) -> None:
    with begin_immediate(fin.engine()) as conn:
        done = {r[0] for r in conn.execute(text("SELECT entry_seq FROM categorizations"))}
        for seq, cp in conn.execute(text("SELECT seq, counterparty FROM entries")).fetchall():
            if seq in done or cp not in RULE_OF:
                continue
            ledger.append(
                conn,
                "categorizations",
                {
                    "entry_seq": seq,
                    "category_id": RULE_OF[cp],
                    "source": "user",
                    "rule_id": None,
                    "proposal_id": None,
                    "created_at": "x",
                },
            )


def set_budget(fin: FinanceDomain, category: str, minor: int) -> None:
    with begin_immediate(fin.engine()) as conn:
        ledger.append(
            conn,
            "budgets",
            {
                "category_id": category,
                "monthly_minor": minor,
                "currency": "CHF",
                "valid_from": "2025-12-01",
                "proposal_id": None,
                "created_at": "x",
            },
        )


def setup_account(fin: FinanceDomain) -> catalog.Account:
    with begin_immediate(fin.engine()) as conn:
        a = catalog.add_account(
            conn,
            institution="BCF",
            name="Compte privé",
            iban=IBAN,
            liquid=True,
            budget_account=True,
        )
        importer.open_account(conn, a.id, "2025-11-30", 100_000, "CHF")
    return a


@pytest.fixture
def ctx(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[HubContext]:
    settings = finance_settings(tmp_path)
    domain = FinanceDomain(settings)
    monkeypatch.setattr(domain, "today", lambda: TODAY)
    hub = HubContext.build(settings, Registry([domain]))
    hub.migrate_all()
    yield hub
    hub.dispose()


@pytest.fixture
def fin(ctx: HubContext) -> FinanceDomain:
    domain = ctx.registry.get("finance")
    assert isinstance(domain, FinanceDomain)
    return domain


@pytest.fixture
def client(ctx: HubContext) -> Iterator[TestClient]:
    with TestClient(create_app(ctx), base_url="https://hub.example.ts.net") as c:
        yield c


@pytest.fixture
def year(fin: FinanceDomain) -> FinanceDomain:
    setup_account(fin)
    fin.importer.process([Incoming(f"{m}.xml", data) for m, data in statements()])
    categorize(fin)
    set_budget(fin, "logement", 150_000)
    set_budget(fin, "alimentation", 25_000)
    return fin


def minor(value: dict[str, object]) -> object:
    return value["minor"]


# --- L2-01 instantanés -------------------------------------------------------------------------


def test_month_ends() -> None:
    assert snapshots.month_ends(date(2025, 11, 30), date(2026, 1, 31)) == [
        date(2025, 11, 30),
        date(2025, 12, 31),
        date(2026, 1, 31),
    ]
    assert snapshots.month_ends(date(2026, 10, 3), date(2026, 10, 27)) == [date(2026, 10, 27)]


def test_series_equals_direct_computation(year: FinanceDomain) -> None:
    stored = rows(year, "SELECT on_date, net_worth_minor, deposits_cum_minor FROM snapshots")
    assert [r[0] for r in stored][:2] == ["2025-11-30", "2025-12-31"]
    assert stored[-1][0] == "2026-10-27"
    assert len(stored) == 12
    with year.engine().connect() as conn:
        direct = [
            (d, v.net_worth, v.deposits)
            for d in (str(r[0]) for r in stored)
            for v in [valuation.value_at(conn, d)]
        ]
        assert snapshots.stored(conn) == snapshots.compute(conn, TODAY)
    assert stored == direct
    assert stored[1][1] == 352_000  # ouverture + décembre
    assert stored[-1][1] == 2_869_000


def test_old_statement_recomputes_the_past(fin: FinanceDomain) -> None:
    setup_account(fin)
    batch = statements(skip={"2026-09"})
    fin.importer.process([Incoming(f"{m}.xml", data) for m, data in batch])
    before = dict(rows(fin, "SELECT on_date, net_worth_minor FROM snapshots"))
    assert before["2026-08-31"] == 100_000 + 9 * 252_000
    (sept,) = [data for m, data in statements() if m == "2026-09"]
    fin.importer.process([Incoming("2026-09.xml", sept)])
    after = dict(rows(fin, "SELECT on_date, net_worth_minor FROM snapshots"))
    assert after["2026-09-30"] == 100_000 + 10 * 252_000
    assert after["2026-10-27"] == 2_869_000
    with fin.engine().connect() as conn:
        assert snapshots.stored(conn) == snapshots.compute(conn, TODAY)


def test_refresh_triggers(year: FinanceDomain) -> None:
    assert year.refresh_snapshots().reason == "current"
    assert year.refresh_snapshots(force=True).reason == "forced"
    later = snapshots.refresh(year.engine(), date(2026, 10, 28))
    assert later.reason == "as_of"
    with begin_immediate(year.engine()) as conn:
        b = catalog.add_account(conn, institution="BCF", name="Épargne", iban=IBAN_2)
        importer.open_account(conn, b.id, "2026-10-01", 50_000, "CHF")
    assert snapshots.refresh(year.engine(), date(2026, 10, 28)).reason == "entries"
    year.nightly()
    assert rows(year, "SELECT as_of FROM snapshot_state") == [("2026-10-27",)]


def test_empty_ledger(fin: FinanceDomain) -> None:
    assert fin.refresh_snapshots().rows == 0
    with fin.engine().connect() as conn:
        assert snapshots.history(conn, None, None)["items"] == []
        k = insights.kpis(conn, "2026-10", TODAY)
    assert minor(k["net_worth"]) == 0
    assert k["months_covered"] is None
    assert k["savings_rate"] is None
    assert k["budget"] is None
    assert k["last_statement"] is None


def test_foreign_currency_needs_a_rate(fin: FinanceDomain) -> None:
    with begin_immediate(fin.engine()) as conn:
        a = catalog.add_account(
            conn, institution="Revolut", name="EUR", currency="EUR", external_ref="rev-eur"
        )
        importer.open_account(conn, a.id, "2026-10-01", 100_000, "EUR")
    with fin.engine().connect() as conn:
        assert valuation.value_at(conn, "2026-10-02").missing_fx == [a.id]
    with begin_immediate(fin.engine()) as conn:
        conn.execute(
            text(
                "INSERT INTO fx_rates (on_date, base, quote, rate, source) "
                "VALUES ('2026-09-30', 'EUR', 'CHF', '0.9375', 'snb')"
            )
        )
    with fin.engine().connect() as conn:
        v = valuation.value_at(conn, "2026-10-02")
    assert (v.net_worth, v.missing_fx) == (93_750, [])


# --- L2-02 routes ------------------------------------------------------------------------------


def test_kpis(client: TestClient, ctx: HubContext, year: FinanceDomain) -> None:
    k = client.get("/api/finance/kpis?month=2026-10", headers=token(ctx, "aggregates")).json()
    assert k["as_of"] == "2026-10-27"
    assert minor(k["net_worth"]) == 2_869_000
    assert minor(k["envelopes"]["cash"]) == 2_869_000
    assert minor(k["change_1m"]["amount"]) == 249_000
    assert k["change_1m"]["since"] == "2026-09-30"
    assert k["change_1m"]["ratio"] == "0.0950"
    # début d'année : le 31 décembre précédent, pas le premier point de l'historique
    assert k["change_ytd"]["since"] == "2025-12-31"
    assert minor(k["change_ytd"]["amount"]) == 2_869_000 - 352_000
    assert minor(k["market_ytd"]) == 0
    assert minor(k["income"]) == 502_000
    assert minor(k["expenses"]) == 193_000
    assert minor(k["savings"]) == 309_000
    assert minor(k["budget"]) == 175_000
    assert minor(k["rest_to_live"]) == -18_000
    assert k["budget_used"] == "1.1029"
    assert k["days_left"] == 4
    assert minor(k["liquid"]) == 2_869_000
    assert k["months_covered"] == "15.3"
    assert k["savings_rate_3m"] == "0.6240"
    assert (k["stale_accounts"], k["to_categorize"]) == (0, 2)
    assert minor(k["pillar3a"]["paid"]) == 600_000
    assert minor(k["pillar3a"]["margin"]) == 125_800
    assert k["last_statement"] == "2026-10-25"
    past = client.get("/api/finance/kpis?month=2026-09", headers=token(ctx, "brain")).json()
    assert (past["as_of"], past["days_left"]) == ("2026-09-30", 0)
    assert (
        client.get("/api/finance/kpis?month=2026-11", headers=token(ctx, "brain")).status_code
        == 422
    )
    assert client.get("/api/finance/kpis", headers=token(ctx, "brain")).json()["month"] == "2026-10"


def test_networth_history(client: TestClient, ctx: HubContext, year: FinanceDomain) -> None:
    h = token(ctx, "aggregates")
    r = client.get("/api/finance/networth/history", headers=h).json()
    assert r["as_of"] == "2026-10-27"
    assert len(r["items"]) == 12
    last = r["items"][-1]
    assert minor(last["net_worth"]) == minor(last["deposits_cum"]) == 2_869_000
    assert set(last["by_envelope"]) == {"cash", "pilier3a", "ibkr", "crypto"}
    part = client.get(
        "/api/finance/networth/history?from=2026-01-01&to=2026-03-31", headers=h
    ).json()
    assert [i["on_date"] for i in part["items"]] == ["2026-01-31", "2026-02-28", "2026-03-31"]


def test_flows_and_rule_of_three(client: TestClient, ctx: HubContext, year: FinanceDomain) -> None:
    full = client.get("/api/finance/flows?month=2026-10", headers=token(ctx, "brain")).json()
    groups = {g["group"]: g for g in full["groups"]}
    assert minor(full["income"]) == 502_000
    assert minor(groups["fixed"]["total"]) == 150_000
    assert minor(groups["variable"]["total"]) == 43_000
    assert minor(groups["savings"]["total"]) == 60_000
    assert minor(full["remainder"]) == 502_000 - 193_000 - 60_000
    variable = {i["category"]: minor(i["total"]) for i in groups["variable"]["items"]}
    assert variable == {"alimentation": 30_000, "restaurants": 8_000, "a-categoriser": 5_000}
    agg = client.get("/api/finance/flows?month=2026-10", headers=token(ctx, "aggregates")).json()
    agg_variable = {g["group"]: g for g in agg["groups"]}["variable"]["items"]
    # une catégorie à moins de 3 écritures n'apparaît pas en portée aggregates
    assert {i["category"] for i in agg_variable} == {"alimentation", "autres"}
    assert {i["category"] for i in agg["sources"]} == {"autres"}


def test_budget_and_totals(client: TestClient, ctx: HubContext, year: FinanceDomain) -> None:
    brain, agg = token(ctx, "brain"), token(ctx, "aggregates")
    b = client.get("/api/finance/budget?month=2026-10", headers=brain).json()
    lines = {line["category"]: line for line in b["lines"]}
    assert lines["alimentation"]["over"] is True
    assert lines["alimentation"]["ratio"] == "1.2000"
    assert lines["logement"]["over"] is False
    assert lines["restaurants"]["target"] is None
    assert (minor(b["rest_to_live"]), b["days_left"], b["over_count"]) == (-18_000, 4, 1)
    a = client.get("/api/finance/budget?month=2026-10", headers=agg).json()
    assert "restaurants" not in {line["category"] for line in a["lines"]}
    q = client.get("/api/finance/budget?month=2026-10&period=q", headers=agg).json()
    assert q["months"] == ["2026-07", "2026-08", "2026-09"]
    q_lines = {line["category"]: line for line in q["lines"]}
    assert minor(q_lines["restaurants"]["spent"]) == 24_000  # trois écritures : visible
    assert minor(q_lines["logement"]["target"]) == 450_000
    t = client.get("/api/finance/budget/totals?month=2026-10&period=q", headers=agg).json()
    assert (minor(t["income"]), minor(t["expenses"]), t["rate"]) == (1_500_000, 564_000, "0.6240")
    assert minor(t["budget"]) == 525_000
    m = client.get("/api/finance/budget/totals?month=2026-10", headers=agg).json()
    assert (minor(m["fixed"]), minor(m["variable"]), minor(m["invested"])) == (
        150_000,
        43_000,
        60_000,
    )
    s = client.get("/api/finance/budget/months?month=2026-10&months=3", headers=agg).json()
    assert [p["month"] for p in s["series"]] == ["2026-08", "2026-09", "2026-10"]
    assert client.get("/api/finance/budget?period=x", headers=agg).status_code == 422


def test_summary_counts_uncategorized(
    client: TestClient, ctx: HubContext, year: FinanceDomain
) -> None:
    s = client.get("/api/finance/summary?month=2026-10", headers=token(ctx, "brain")).json()
    assert (minor(s["income"]), minor(s["expenses"]), minor(s["uncategorized"])) == (
        502_000,
        193_000,
        -3_000,
    )


def test_export_csv(client: TestClient, ctx: HubContext, year: FinanceDomain) -> None:
    assert client.get("/api/finance/export.csv", headers=token(ctx, "brain")).status_code == 403
    app_session(ctx, client)
    r = client.get("/api/finance/export.csv?from=2026-10-01")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert r.headers["content-disposition"] == 'attachment; filename="finance-2026-10-27.csv"'
    table = list(csv.DictReader(io.StringIO(r.text)))
    assert len(table) == 9
    rent = next(x for x in table if x["counterparty"] == "Régie Fictive")
    assert (rent["amount"], rent["category"], rent["account_iban"]) == (
        "-1500.00",
        "logement",
        IBAN,
    )
    everything = list(csv.DictReader(io.StringIO(client.get("/api/finance/export.csv").text)))
    assert len(everything) == 1 + 11 * 7 + 2  # ouverture comprise


def test_export_neutralizes_formulas() -> None:
    assert insights._cell("=HYPERLINK()") == "'=HYPERLINK()"
    assert insights._cell("Migros") == "Migros"
    assert insights._cell(None) == ""


def test_ratio_and_periods() -> None:
    assert insights.ratio(1, 3) == "0.3333"
    assert insights.ratio(1, 0) is None
    assert insights.period_months("2026-01", "q") == ["2025-10", "2025-11", "2025-12"]
    assert insights.days_left("2026-02", date(2026, 2, 10)) == 18
    with pytest.raises(insights.FutureMonth):
        insights.as_of("2026-11", TODAY)
