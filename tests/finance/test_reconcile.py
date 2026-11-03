"""Rapprochement et ruptures (docs/finance-politique.md) : aucun solde ne vient de nulle part.
Des parts sans historique, un envoi ou une arrivée hors des comptes suivis, un cours absent ou
ancien deviennent des ruptures chiffrées ; ta décision les règle, et le coût saisi entre dans le
résultat depuis l'achat comme dans la performance."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient

from hub.core.context import HubContext
from hub.core.errors import Problem
from hub.domains.finance.domain import FinanceDomain
from hub.domains.finance.patrimoine.app import assets, crypto_cost, reconcile, valuation
from hub.domains.finance.patrimoine.model import positions
from hub.domains.finance.patrimoine.model.fx import FxRates
from hub.platform.db import begin_immediate
from tests.finance.conftest import ready_account
from tests.finance.test_crypto_cost import _crypto_gain, btc, doc, minor, setup
from tests.finance.test_exchange import op
from tests.finance.test_finance_api import app_session, client, ctx, fin  # noqa: F401 (fixtures)
from tests.finance.test_wealth import add_ref

ON = "2026-10-27"


@pytest.fixture
def client_fin(
    ctx: HubContext,  # noqa: F811
    client: TestClient,  # noqa: F811
    fin: FinanceDomain,  # noqa: F811
) -> tuple[TestClient, FinanceDomain]:
    app_session(ctx, client)
    return client, fin


def sol(on: str, price: str) -> dict[str, str]:
    return {
        "instrument": "SOL",
        "kind": "crypto",
        "on_date": on,
        "price": price,
        "currency": "CHF",
        "source": "coingecko",
    }


def phantom(finance: FinanceDomain, quantity: str = "2") -> None:
    """2 SOL relevés sur un portefeuille, sans aucune opération pour les expliquer (un compte
    bancaire ouvert avant : la performance commence avant les cryptos)."""
    ready_account(finance, 100_000)
    add_ref(finance, "crypto:phantom", "crypto", "Phantom")
    balance = {"account": "crypto:phantom", "instrument": "SOL", "on_date": "2026-10-01"}
    finance.importer.process(
        [
            doc(
                prices=[sol("2026-10-01", "100"), sol("2026-10-26", "100")],
                balances=[{**balance, "quantity": quantity}],
            )
        ]
    )


def breaks(finance: FinanceDomain, on: str = ON) -> dict[str, Any]:
    with finance.engine().connect() as conn:
        return reconcile.summary(conn, on)


def decide(finance: FinanceDomain, break_id: str, decision: str, cost: int | None = None) -> None:
    with begin_immediate(finance.engine()) as conn:
        reconcile.decide(conn, ON, break_id, decision, cost_minor=cost, note=None, actor="t")


def test_coins_without_history_are_a_break_until_their_cost_is_given(
    finance: FinanceDomain,
) -> None:
    phantom(finance)
    r = breaks(finance)
    (b,) = r["items"]
    assert (b["kind"], b["symbol"], b["quantity"], b["cause"]) == (
        "unexplained",
        "SOL",
        "2",
        "no_history",
    )
    assert (minor(b["value"]), b["since"], b["actions"]) == (
        20_000,
        "2026-10-01",
        ["import", "cost", "accept"],
    )
    assert r["completeness"] == "0.000"
    # tu saisis ce que ces 2 SOL ont coûté : 150 CHF ; ils entrent à ce coût, le 1er octobre
    decide(finance, b["id"], "cost", 15_000)
    r = breaks(finance)
    assert (r["count"], r["completeness"]) == (0, "1.000")
    with finance.engine().connect() as conn:
        res = crypto_cost.result(conn, ON, valuation.Positions(conn))
    assert res is not None
    assert (minor(res["cost"]), minor(res["result"]), minor(res["unknown_cost_value"])) == (
        15_000,
        5_000,
        0,
    )
    assert _crypto_gain(finance, ON) == 5_000  # la performance part du même coût


def test_kept_as_is_coins_enter_at_their_value_when_they_appeared(finance: FinanceDomain) -> None:
    phantom(finance)
    (b,) = breaks(finance)["items"]
    decide(finance, b["id"], "accept")
    assert breaks(finance)["count"] == 0
    with finance.engine().connect() as conn:
        res = crypto_cost.result(conn, ON, valuation.Positions(conn))
    assert res is not None
    assert (minor(res["cost"]), minor(res["result"])) == (20_000, 0)
    # de nouvelles parts sans historique rouvrent une rupture, pour elles seules
    finance.importer.process(
        [
            doc(
                balances=[
                    {
                        "account": "crypto:phantom",
                        "instrument": "SOL",
                        "on_date": "2026-10-20",
                        "quantity": "3",
                    }
                ]
            )
        ]
    )
    (again,) = breaks(finance)["items"]
    assert (again["quantity"], minor(again["value"])) == ("1", 10_000)


def test_a_small_gap_stays_under_the_tolerance(finance: FinanceDomain) -> None:
    phantom(finance, "0.005")  # 0,50 CHF
    assert breaks(finance)["count"] == 0


def test_transfers_between_my_accounts_are_not_breaks(finance: FinanceDomain) -> None:
    setup(finance)  # Binance → Ledger relié, récompense, vente : tout s'explique
    # (seul le cours, vieux du 1er octobre, est signalé)
    assert {b["kind"] for b in breaks(finance)["items"]} == {"stale_price"}


def test_a_send_to_an_untracked_wallet_is_a_break_until_marked_gone(
    finance: FinanceDomain,
) -> None:
    add_ref(finance, "crypto:binance", "crypto", "Binance")
    finance.importer.process(
        [
            doc(
                prices=[btc("2026-03-01", "50000"), btc("2026-10-01", "40000")],
                operations=[
                    op("fiat:1", "fiat_deposit", "2026-03-01", ("CHF", "1000", "deposit")),
                    op(
                        "buy:1",
                        "trade",
                        "2026-03-02",
                        ("CHF", "-1000", "trade"),
                        ("BTC", "0.02", "trade"),
                    ),
                    op("out:1", "withdrawal", "2026-04-01", ("BTC", "-0.01", "withdrawal")),
                ],
            )
        ]
    )
    (b,) = [x for x in breaks(finance)["items"] if x["kind"] != "stale_price"]
    assert (b["kind"], minor(b["value"]), b["since"], b["actions"]) == (
        "sent_outside",
        50_000,
        "2026-04-01",
        ["add_wallet", "gone"],
    )
    decide(finance, b["id"], "gone")
    assert {x["kind"] for x in breaks(finance)["items"]} == {"stale_price"}
    with pytest.raises(Problem):
        decide(finance, b["id"], "gone")  # déjà réglée


def test_a_held_coin_without_price_or_with_an_old_one(finance: FinanceDomain) -> None:
    add_ref(finance, "crypto:phantom", "crypto", "Phantom")
    held = {"account": "crypto:phantom", "on_date": "2026-10-01", "quantity": "1"}
    finance.importer.process(
        [
            doc(
                prices=[sol("2026-10-01", "100")],
                balances=[{**held, "instrument": "SOL"}, {**held, "instrument": "BONK"}],
            )
        ]
    )
    kinds = {(b["kind"], b["symbol"]) for b in breaks(finance)["items"]}
    assert ("no_price", "BONK") in kinds
    assert ("stale_price", "SOL") in kinds  # dernier cours le 1er octobre
    assert ("stale_price", "SOL") not in {
        (b["kind"], b["symbol"]) for b in breaks(finance, "2026-10-03")["items"]
    }


def test_a_no_price_decision_covers_the_parts_it_saw(finance: FinanceDomain) -> None:
    """« Garder tel quel » sans cours couvre ces parts-là (audit M7) : si les parts changent, la
    rupture se rouvre au lieu de valoir 0 à vie."""
    add_ref(finance, "crypto:phantom", "crypto", "Phantom")
    held = {"account": "crypto:phantom", "instrument": "BONK", "on_date": "2026-10-01"}
    finance.importer.process([doc(balances=[{**held, "quantity": "1"}])])

    def no_price() -> list[dict[str, Any]]:
        return [x for x in breaks(finance)["items"] if x["kind"] == "no_price"]

    (b,) = no_price()
    assert b["quantity"] == "1"
    decide(finance, b["id"], "accept")
    assert no_price() == []
    with finance.engine().connect() as conn:
        (d,) = reconcile.decisions.read(conn)
    assert (d.break_kind, d.quantity) == ("no_price", Decimal("1"))
    finance.importer.process([doc(balances=[{**held, "on_date": "2026-10-20", "quantity": "3"}])])
    (again,) = no_price()
    assert again["quantity"] == "3"


def test_an_old_exchange_rate_is_said_like_an_old_price(finance: FinanceDomain) -> None:
    """Un change plus vieux que 7 jours convertit encore, mais ouvre une rupture « change
    ancien » (audit M6) ; la décision la couvre jusqu'au change qu'elle a vu."""
    add_ref(finance, "crypto:phantom", "crypto", "Phantom")
    held = {"account": "crypto:phantom", "instrument": "SOL", "on_date": ON, "quantity": "1"}
    finance.importer.process([doc(prices=[{**sol(ON, "100"), "currency": "USD"}], balances=[held])])
    with begin_immediate(finance.engine()) as conn:
        assets.add_fx(conn, "2026-10-10", "USD", "CHF", Decimal("0.8"), "test")
    rep = breaks(finance)
    (b,) = [x for x in rep["items"] if x["kind"] == "stale_fx"]
    assert (b["symbol"], b["since"], b["actions"]) == ("USD", "2026-10-10", ["accept"])
    assert rep["invested"]["minor"] == 8_000  # converti quand même, jamais 0 en silence
    decide(finance, b["id"], "accept")
    assert not [x for x in breaks(finance)["items"] if x["kind"] == "stale_fx"]
    with begin_immediate(finance.engine()) as conn:  # un change plus récent, encore trop vieux
        assets.add_fx(conn, "2026-10-29", "USD", "CHF", Decimal("0.81"), "test")
    assert [
        x["since"] for x in breaks(finance, "2026-11-10")["items"] if x["kind"] == "stale_fx"
    ] == ["2026-10-29"]


def test_breaks_route_and_decision(
    client_fin: tuple[TestClient, FinanceDomain],
    ctx: HubContext,  # noqa: F811
) -> None:
    """La décision est une proposition (`decide_break`, Double Sas) : aperçu, validation, et
    un retrait qui rouvre la rupture (`withdraw_break_decision`)."""
    from hub.core import proposals
    from tests.finance.test_double_sas import APP, accept, create

    http, domain = client_fin
    today = domain.today()
    add_ref(domain, "crypto:phantom", "crypto", "Phantom")
    first = (today - timedelta(days=5)).isoformat()
    domain.importer.process(
        [
            doc(
                prices=[sol(first, "100"), sol(today.isoformat(), "100")],
                balances=[
                    {
                        "account": "crypto:phantom",
                        "instrument": "SOL",
                        "on_date": first,
                        "quantity": "2",
                    }
                ],
            )
        ]
    )
    r = http.get("/api/finance/breaks").json()
    assert r["count"] == 1
    (b,) = r["items"]
    assert b["account"] == "Phantom"
    with pytest.raises(Problem):  # « parti » ne règle pas des parts sans historique
        create(ctx, "decide_break", {"break_id": b["id"], "decision": "gone"})
    with pytest.raises(Problem):  # un coût saisi demande son montant
        create(ctx, "decide_break", {"break_id": b["id"], "decision": "cost"})
    p = create(ctx, "decide_break", {"break_id": b["id"], "decision": "cost", "cost_minor": 15_000})
    assert p.preview["summary"].startswith("Rupture « parts sans historique » sur Phantom (SOL)")
    assert p.preview["details"]["break"]["id"] == b["id"]
    outcome = accept(ctx, p)
    assert outcome.status == "applied"
    assert outcome.result is not None
    assert outcome.result["decision"]["cost_minor"] == 15_000
    assert http.get("/api/finance/breaks").json()["count"] == 0
    with domain.engine().connect() as conn:
        (d,) = reconcile.decisions.read(conn)
    assert d.proposal_id == p.id
    # un retrait (l'inverse) rouvre la rupture ; la décision reste dans l'historique
    with ctx.core.engine.connect() as conn:
        fresh = proposals.get(conn, p.id)
    reverted = proposals.revert(ctx, APP, fresh, None)
    assert reverted.status == "applied"
    assert http.get("/api/finance/breaks").json()["count"] == 1
    with domain.engine().connect() as conn:
        assert reconcile.decisions.read(conn) == []
        assert reconcile.decisions.get(conn, d.id) is None
    with pytest.raises(Problem):
        create(ctx, "withdraw_break_decision", {"decision_id": d.id})


def test_verify_checks_the_figures(finance: FinanceDomain) -> None:
    # le hub contrôle ses chiffres : un seul gain pour les cryptos, ruptures comptées
    setup(finance)
    phantom(finance)
    health = finance.verify()
    assert health.ok
    fig = health.detail["figures"]
    assert fig["by_kind"]["unexplained"] == 1
    crypto = fig["crypto"]
    assert crypto["ok"]
    # la performance compte les 2 SOL sans historique à leur cours ; le résultat les laisse à part
    gap = abs(minor(crypto["performance_max"]) - minor(crypto["since_purchase"]))
    assert gap <= minor(crypto["allowed_gap"])


class _Positions(positions.Positions):
    """Relevés et mouvements d'un compte, un cours de 500 la part, en francs."""

    def __init__(self, reports: Any, trades: Any) -> None:
        super().__init__(FxRates("CHF", {}), {"a": trades}, {"a": reports}, {})

    def price(self, isin: str, on_date: str) -> positions.Price | None:
        return on_date, Decimal(500), "CHF"


def test_a_fund_report_rounded_to_the_hundredth_is_not_a_break() -> None:
    """VIAC arrondit les parts au centième : 12.35 puis 12.36 avec un achat de 0.003 part, c'est
    l'arrondi (7 millièmes, 3,50 CHF) ; 12.36 puis 12.40 sans achat, ce sont des parts qui
    manquent."""
    one = Decimal("1")
    reports = [
        ("2026-01-31", {"CH1": (Decimal("12.35"), one, "CHF")}),
        ("2026-02-28", {"CH1": (Decimal("12.36"), one, "CHF")}),
    ]
    trades = [("2026-02-10", "CH1", Decimal("0.003"))]
    p: Any = _Positions(reports, trades)
    assert reconcile._unexplained(p, "a", "pillar3a", "2026-03-01", {}) == []
    later = [*reports, ("2026-03-31", {"CH1": (Decimal("12.40"), one, "CHF")})]
    (b,) = reconcile._unexplained(_Positions(later, trades), "a", "pillar3a", "2026-04-01", {})
    assert (b.asset, b.quantity) == ("CH1", Decimal("0.04"))


def test_a_renamed_coin_counts_under_its_new_name() -> None:
    one = Decimal("1")
    reports = [("2026-06-01", {"CRYPTO:RENDER": (Decimal("5"), one, "CHF")})]
    trades = [("2026-01-01", "CRYPTO:RNDR", Decimal("5"))]  # acheté sous l'ancien nom
    p: Any = _Positions(reports, trades)
    assert reconcile._unexplained(p, "a", "crypto", "2026-06-02", {}) == []
