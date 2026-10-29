"""Performance du patrimoine : flux au bon niveau, rendement pondéré dans le temps, gain,
rendement personnel, change, cours manquants, dettes, et la route."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, text

from hub.core.context import HubContext
from hub.core.db import begin_immediate
from hub.domains.finance import assets, catalog, debts, ledger, performance, valuation
from hub.domains.finance.domain import FinanceDomain
from tests.finance.conftest import add_account, open_account
from tests.finance.test_double_sas import client, ctx, fin
from tests.finance.test_finance_api import token

__all__ = ["client", "ctx", "fin"]  # fixtures
FUND = "IE00B4L5Y983"  # forme valide, fictif pour le test
SAVINGS_IBAN = "CH5604835012345678009"


def ref(fin: FinanceDomain, external: str, kind: str, currency: str = "CHF") -> catalog.Account:
    with begin_immediate(fin.engine()) as conn:
        return catalog.add_account(
            conn,
            institution="Test",
            name=external,
            kind=kind,
            external_ref=external,
            currency=currency,
        )


def entry(
    conn: Connection, account: catalog.Account, on: str, amount: int, code: str | None = None
) -> None:
    ledger.append_entry(
        conn,
        ledger.NewEntry(
            account_id=account.id,
            booking_date=on,
            amount_minor=amount,
            currency=account.currency,
            bank_tx_code=code,
            label="test",
            dedup_key=ledger.dedup_hash(f"perf|{account.id}|{on}|{amount}|{code}"),
        ),
    )


def trade(conn: Connection, account: catalog.Account, on: str, qty: str, amount: int) -> None:
    ledger.append(
        conn,
        "trades",
        {
            "account_id": account.id,
            "trade_date": on,
            "isin": FUND,
            "quantity": qty,
            "amount_minor": amount,
            "currency": "CHF",
            "dedup_key": f"perf|{account.id}|{on}|{qty}",
            "import_id": None,
            "created_at": "2026-10-29T00:00:00.000Z",
        },
    )


def price(conn: Connection, on: str, value: str) -> None:
    assets.upsert_instrument(conn, FUND, "Fonds test", kind="fund", currency="CHF")
    assets.add_price(conn, FUND, on, Decimal(value), "CHF", "test", None)


def run(fin: FinanceDomain, as_of: str, ids: list[str] | None = None, **kw: Any) -> dict[str, Any]:
    with fin.engine().connect() as conn:
        eng = performance.build(conn, as_of)
    assert eng is not None
    return performance.report(eng, ids, kw.get("start"), kw.get("end"), kw.get("step", "day"))


def chf(m: dict[str, Any]) -> int:
    return int(m["minor"])


def rate(x: str | None) -> float:
    assert x is not None
    return float(x)


# --- comptes bancaires : salaire, dépenses, virement entre mes comptes ---------------------------


@pytest.fixture
def banks(fin: FinanceDomain) -> tuple[catalog.Account, catalog.Account]:
    bcf = add_account(fin)
    savings = add_account(fin, iban=SAVINGS_IBAN)
    open_account(fin, bcf, "2026-01-01", 100_000)
    open_account(fin, savings, "2026-01-01", 500_000)
    with begin_immediate(fin.engine()) as conn:
        entry(conn, bcf, "2026-01-25", 650_000)  # salaire
        entry(conn, bcf, "2026-01-28", -400_000)  # dépenses
        entry(conn, bcf, "2026-01-29", -100_000)  # virement vers l'épargne…
        entry(conn, savings, "2026-01-29", 100_000)  # … reçu
    return bcf, savings


def test_saving_is_not_performance(fin: FinanceDomain, banks: Any) -> None:
    bcf, savings = banks
    out = run(fin, "2026-01-31")
    s = out["summary"]
    # 6000 + 2500 avant, puis +2500 d'épargne : rien n'est un gain
    assert chf(s["start"]) == 600_000
    assert chf(s["end"]) == 850_000
    assert chf(s["net_flows"]) == 250_000  # salaire − dépenses ; le virement interne s'annule
    assert chf(s["gain"]) == 0
    assert rate(s["twr"]) == pytest.approx(0)
    # pour chaque compte, le virement est un flux
    assert chf(out["by_account"][bcf.id]["net_flows"]) == 150_000
    assert chf(out["by_account"][savings.id]["net_flows"]) == 100_000
    assert chf(out["by_account"][savings.id]["gain"]) == 0
    assert out["summary"]["complete"] is True


def test_interest_and_fees_are_market(fin: FinanceDomain, banks: Any) -> None:
    _bcf, savings = banks
    with begin_immediate(fin.engine()) as conn:
        entry(conn, savings, "2026-01-30", 1_500, code="VIAC/INCOME/INTEREST")
        entry(conn, savings, "2026-01-30", -300, code="VIAC/FEE")
    out = run(fin, "2026-01-31", [f"{savings.id}|cash"])
    s = out["summary"]
    assert chf(s["income"]) == 1_500
    assert chf(s["fees"]) == -300
    assert chf(s["gain"]) == 1_200
    assert chf(s["net_flows"]) == 100_000
    assert rate(s["twr"]) > 0


# --- un placement : achats, cours, ouverture en cours de période ---------------------------------


@pytest.fixture
def fund(fin: FinanceDomain) -> catalog.Account:
    acc = ref(fin, "test:titres", "securities")
    with begin_immediate(fin.engine()) as conn:
        price(conn, "2026-03-01", "100")
        trade(conn, acc, "2026-03-01", "10", 100_000)  # 1000 CHF
        price(conn, "2026-03-10", "110")  # +10 %
        trade(conn, acc, "2026-03-10", "10", 110_000)  # on double la mise au nouveau cours
        price(conn, "2026-03-20", "99")  # −10 %
    return acc


def test_time_weighted_return_ignores_deposits(fin: FinanceDomain, fund: catalog.Account) -> None:
    out = run(fin, "2026-03-31")
    s = out["summary"]
    assert chf(s["end"]) == 20 * 9_900
    assert chf(s["start"]) == 100_000  # le premier jour ouvre la période
    assert chf(s["net_flows"]) == 110_000  # le second achat est un flux
    assert chf(s["gain"]) == 198_000 - 210_000
    # +10 % puis −10 % : −1 %, quel que soit le montant versé entre les deux
    assert rate(s["twr"]) == pytest.approx(1.1 * 0.9 - 1, abs=1e-6)
    line = out["by_line"][f"{fund.id}|{FUND}"]
    assert line["twr"] == s["twr"]
    asset = out["by_asset"][f"isin:{FUND}"]
    assert chf(asset["gain"]) == -12_000


def test_fees_of_a_positions_account_split_the_gain(
    fin: FinanceDomain, fund: catalog.Account
) -> None:
    with begin_immediate(fin.engine()) as conn:
        entry(conn, fund, "2026-03-15", -1_500, "VIAC/FEE")
    out = run(fin, "2026-03-31")
    s = out["summary"]
    # la valeur suit les parts : les frais ne changent pas le gain, ils le décomposent
    assert chf(s["gain"]) == 198_000 - 210_000
    assert chf(s["fees"]) == -1_500
    assert chf(s["price_effect"]) == chf(s["gain"]) + 1_500
    assert chf(out["by_account"][fund.id]["fees"]) == -1_500


def test_period_inside_history(fin: FinanceDomain, fund: catalog.Account) -> None:
    out = run(fin, "2026-03-31", start="2026-03-10")
    s = out["summary"]
    assert chf(s["start"]) == 20 * 11_000  # la valeur du jour de départ, achat du jour compris
    assert chf(s["net_flows"]) == 0
    assert rate(s["twr"]) == pytest.approx(-0.1, abs=1e-6)
    assert s["mwr"] is None  # moins d'un an


def test_values_match_the_valuation(fin: FinanceDomain, banks: Any, fund: catalog.Account) -> None:
    with fin.engine().connect() as conn:
        eng = performance.build(conn, "2026-03-31")
        assert eng is not None
        for on in ("2026-01-15", "2026-01-31", "2026-03-05", "2026-03-31"):
            k = eng.index(on)
            total = sum(
                ln.value[k] for ln in eng.lines.values() if ln.value[k] != performance.ABSENT
            )
            assert total == valuation.value_at(conn, on).net_worth


# --- change, cours manquants ---------------------------------------------------------------------


def test_currency_moves_are_market(fin: FinanceDomain) -> None:
    eur = ref(fin, "test:eur", "cash", currency="EUR")
    open_account(fin, eur, "2026-02-01", 100_000)  # 1000 EUR
    with begin_immediate(fin.engine()) as conn:
        assets.add_fx(conn, "2026-02-01", "EUR", "CHF", Decimal("0.95"), "test")
        assets.add_fx(conn, "2026-02-15", "EUR", "CHF", Decimal("0.90"), "test")
    s = run(fin, "2026-02-28")["summary"]
    assert chf(s["start"]) == 95_000
    assert chf(s["end"]) == 90_000
    assert chf(s["net_flows"]) == 0
    assert chf(s["gain"]) == -5_000
    assert chf(s["price_effect"]) == -5_000
    assert rate(s["twr"]) == pytest.approx(0.90 / 0.95 - 1, abs=1e-6)


def test_first_price_is_a_flow_and_marked(fin: FinanceDomain) -> None:
    acc = ref(fin, "test:titres2", "securities")
    with begin_immediate(fin.engine()) as conn:
        trade(conn, acc, "2026-04-01", "5", 50_000)
        price(conn, "2026-04-05", "100")
    out = run(fin, "2026-04-10")
    s = out["summary"]
    # sans cours du 1er au 4 avril, le compte est porté au registre (aucune écriture : 0) ;
    # son premier cours n'est pas un gain
    assert chf(s["gain"]) == 0
    assert chf(s["end"]) == 50_000
    assert s["complete"] is False
    assert out["missing"] == [f"{acc.id}|cash"]


# --- dette ----------------------------------------------------------------------------------------


def test_debt_interest_is_a_loss_and_payments_cancel(
    fin: FinanceDomain, monkeypatch: pytest.MonkeyPatch
) -> None:
    bcf = add_account(fin)
    open_account(fin, bcf, "2026-01-01", 1_000_000)
    with begin_immediate(fin.engine()) as conn:
        conn.execute(
            text(
                "INSERT INTO debts (id, name, lender, kind, currency, rate, category_id, "
                "account_id, created_at, updated_at) VALUES ('d1', 'Crédit', 'Prêteur', 'loan', "
                "'CHF', '0.0365', 'voiture-credit', :a, 'x', 'x')"
            ),
            {"a": bcf.id},
        )
        debts.record_balance(conn, "d1", "2026-01-01", 500_000, "opening", None)
        entry(conn, bcf, "2026-01-11", -100_000)
        (seq,) = conn.execute(text("SELECT seq FROM entries WHERE amount_minor = -100000")).one()
        ledger.append(
            conn,
            "categorizations",
            {
                "entry_seq": seq,
                "category_id": "voiture-credit",
                "source": "user",
                "rule_id": None,
                "proposal_id": None,
                "created_at": "x",
            },
        )
    out = run(fin, "2026-01-21")
    debt = out["by_account"]["debt:d1"]
    # 10 jours à 3,65 % sur 5000 = 5 CHF, puis 10 jours sur 4005 ≈ 4 CHF
    assert chf(debt["net_flows"]) == 100_000
    assert chf(debt["gain"]) == pytest.approx(-901, abs=2)
    assert debt["twr"] is None  # une dette n'a pas de rendement
    s = out["summary"]
    assert chf(s["net_flows"]) == 0  # le paiement passe d'une ligne à l'autre
    assert chf(s["gain"]) == chf(debt["gain"])


# --- rendement personnel, risque, périodes -------------------------------------------------------


def test_money_weighted_return_over_a_year(fin: FinanceDomain) -> None:
    acc = ref(fin, "test:titres3", "securities")
    with begin_immediate(fin.engine()) as conn:
        price(conn, "2025-01-01", "100")
        trade(conn, acc, "2025-01-01", "10", 100_000)
        price(conn, "2025-07-01", "90")
        price(conn, "2026-01-01", "110")
    out = run(fin, "2026-01-01")
    s = out["summary"]
    assert rate(s["twr"]) == pytest.approx(0.10, abs=1e-6)
    assert rate(s["mwr"]) == pytest.approx(0.10, abs=1e-4)
    assert rate(s["twr_yearly"]) == pytest.approx(0.10, abs=1e-4)
    risk = out["risk"]
    assert rate(risk["max_drawdown"]) == pytest.approx(-0.10, abs=1e-6)
    assert risk["peak_on"] == "2025-01-01"
    assert risk["trough_on"] == "2025-07-01"
    assert risk["recovered_on"] == "2025-12-31" or risk["recovered_on"] == "2026-01-01"
    years = [y["period"] for y in out["by_year"]]
    assert years == ["2025", "2026"]
    assert len(out["by_month"]) == 13
    assert len(run(fin, "2026-01-01", step="month")["items"]) == 14


def test_route(
    client: TestClient,
    ctx: HubContext,
    fin: FinanceDomain,
    banks: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bcf, _savings = banks
    monkeypatch.setattr(fin, "today", lambda: date(2026, 1, 31))
    r = client.get(
        "/api/finance/performance",
        params={"from": "2026-01-01", "step": "week", "line": [f"{bcf.id}|cash"]},
        headers=token(ctx, "brain"),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["lines"] == 1
    assert body["items"][0]["on_date"] == "2026-01-01"
    assert body["items"][-1]["on_date"] == "2026-01-31"
    assert chf(body["summary"]["net_flows"]) == 150_000
    assert set(body["by_account"]) == {bcf.id}
