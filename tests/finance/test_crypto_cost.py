"""Résultat des cryptos depuis l'achat : prix de revient commun à tous les comptes, virement
entre mes comptes sans remise à zéro du coût, récompense sans coût, vente réalisée, effet du
dollar, et parts sans historique montrées à part."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from sqlalchemy import text

from hub.domains.finance.domain import FinanceDomain
from hub.domains.finance.patrimoine.app import (
    assets,
    crypto_cost,
    holdings,
    perf_lines,
    performance,
    valuation,
)
from hub.domains.finance.patrimoine.model import instruments
from hub.domains.finance.sources.infra import market_file
from hub.domains.finance.sources.infra.files import Incoming
from hub.platform.db import begin_immediate
from tests.finance.test_exchange import op
from tests.finance.test_wealth import add_ref


def doc(**kw: Any) -> Incoming:
    body = {"format": market_file.FORMAT, "fetched_at": "2026-10-27", **kw}
    return Incoming("market.json", json.dumps(body).encode())


def btc(on: str, value: str) -> dict[str, str]:
    return {
        "instrument": "BTC",
        "kind": "crypto",
        "on_date": on,
        "price": value,
        "currency": "CHF",
        "source": "coingecko",
    }


def usd(on: str, rate: str) -> dict[str, str]:
    return {"on_date": on, "base": "USD", "quote": "CHF", "rate": rate, "source": "ecb"}


def minor(x: dict[str, Any] | None) -> int | None:
    return None if x is None else int(x["minor"])


def setup(finance: FinanceDomain) -> None:
    add_ref(finance, "crypto:binance", "crypto", "Binance")
    add_ref(finance, "crypto:ledger", "crypto", "Ledger")
    binance = doc(
        fx=[usd("2026-03-01", "0.9"), usd("2026-10-01", "0.8")],
        prices=[
            btc("2026-03-01", "50000"),
            btc("2026-04-01", "80000"),
            btc("2026-06-01", "60000"),
            btc("2026-10-01", "40000"),
        ],
        operations=[
            op("fiat:1", "fiat_deposit", "2026-03-01", ("CHF", "1000", "deposit")),
            op("buy:1", "trade", "2026-03-02", ("CHF", "-1000", "trade"), ("BTC", "0.02", "trade")),
            op("out:1", "withdrawal", "2026-04-01", ("BTC", "-0.01", "withdrawal"), txid="t1"),
            op("reward:1", "reward", "2026-04-01", ("BTC", "0.001", "income")),
            op(
                "sell:1", "trade", "2026-06-01", ("BTC", "-0.005", "trade"), ("CHF", "300", "trade")
            ),
        ],
    )
    ledger = doc(
        transactions=[
            {
                "account": "crypto:ledger",
                "instrument": "BTC",
                "on_date": "2026-04-01",
                "txid": "t1",
                "quantity": "0.01",
                "fee": "0",
            }
        ]
    )
    finance.importer.process([binance])
    finance.importer.process([ledger])


def test_cost_follows_the_coins_across_my_accounts(finance: FinanceDomain) -> None:
    setup(finance)
    with finance.engine().connect() as conn:
        r = holdings.holdings(conn, "2026-10-27")["crypto"]["since_purchase"]
    assert r is not None
    # 0.016 BTC à 40 000 ; payés 1 000 pour 0.02, l'envoi vers la Ledger garde le coût,
    # la récompense entre sans coût, la vente de 0.005 sort 0.005 / 0.021 du coût
    assert minor(r["value"]) == 64_000
    assert minor(r["cost"]) == 76_190
    assert minor(r["realized"]) == 6_190  # 300 − 238,10
    assert minor(r["unrealized"]) == -12_190
    assert minor(r["result"]) == -6_000
    assert minor(r["income"]) == 8_000  # 0.001 à 80 000, le jour de la récompense
    assert minor(r["unknown_cost_value"]) == 0
    assert minor(r["arrived_from_outside"]) == 0
    # en dollars, les cryptos ont gagné ; c'est le dollar (0,90 → 0,80) qui fait la perte
    assert (minor(r["result_usd"]), r["result_usd"]["currency"]) == (2_222, "USD")
    assert minor(r["crypto_effect"]) == 1_778
    assert minor(r["fx_effect"]) == -7_778
    assert set(r["by_asset"]) == {"CRYPTO:BTC"}
    assert minor(r["by_asset"]["CRYPTO:BTC"]["result"]) == -6_000


def test_coins_without_history_have_no_cost(finance: FinanceDomain) -> None:
    add_ref(finance, "crypto:phantom", "crypto", "Phantom")
    sol = {"kind": "crypto", "currency": "CHF", "source": "coingecko", "instrument": "SOL"}
    finance.importer.process(
        [
            doc(
                prices=[{**sol, "on_date": "2026-10-01", "price": "100"}],
                balances=[
                    {
                        "account": "crypto:phantom",
                        "instrument": "SOL",
                        "on_date": "2026-10-01",
                        "quantity": "2",
                    }
                ],
            )
        ]
    )
    with finance.engine().connect() as conn:
        r = holdings.holdings(conn, "2026-10-27")["crypto"]["since_purchase"]
    assert r is not None
    assert (minor(r["value"]), minor(r["cost"]), minor(r["result"])) == (20_000, 0, 0)
    assert minor(r["unknown_cost_value"]) == 20_000


def test_roles_from_codes() -> None:
    assert crypto_cost.role("EXCHANGE/TRADE/BUY") == "trade"
    assert crypto_cost.role("SWISSBORG/INCOME/YIELD") == "income"
    assert crypto_cost.role("CRYPTO/FEE") == "fee"
    assert crypto_cost.role("CRYPTO/RECEIVE") == "in"
    assert crypto_cost.role("SWISSBORG/WITHDRAWAL") == "out"
    assert crypto_cost.role("OPENING") is None


def test_nothing_held_and_history_below_zero(finance: FinanceDomain) -> None:
    # tout est parti, et l'historique sort plus de parts qu'il n'en a fait entrer : pas de
    # division par zéro, rien de tenu, rien de latent
    add_ref(finance, "crypto:binance", "crypto", "Binance")
    finance.importer.process(
        [
            doc(
                fx=[usd("2026-03-01", "0.9")],
                prices=[btc("2026-03-01", "50000"), btc("2026-10-01", "40000")],
                balances=[
                    {
                        "account": "crypto:binance",
                        "instrument": "BTC",
                        "on_date": "2026-03-01",
                        "quantity": "0.01",
                    }
                ],
                operations=[
                    op("out:1", "withdrawal", "2026-03-02", ("BTC", "-0.01", "withdrawal")),
                ],
            )
        ]
    )
    with finance.engine().connect() as conn:
        r = crypto_cost.result(conn, "2026-10-27", valuation.Positions(conn))
    assert r is not None
    assert (minor(r["value"]), minor(r["cost"]), minor(r["unrealized"])) == (0, 0, 0)
    assert minor(r["unknown_cost_value"]) == 0


def test_a_report_at_zero_for_held_coins_is_not_a_value(finance: FinanceDomain) -> None:
    # SwissBorg relève des parts sans cours du jour : valeur 0. Ce n'est pas une valeur nulle,
    # la ligne vaut parts × cours (sinon une fausse perte, puis un faux gain le lendemain)
    account = add_ref(finance, "crypto:phantom", "crypto", "Phantom")
    sol = {"kind": "crypto", "currency": "CHF", "source": "coingecko", "instrument": "SOL"}
    finance.importer.process(
        [
            doc(
                prices=[
                    {**sol, "on_date": "2026-10-01", "price": "100"},
                    {**sol, "on_date": "2026-10-02", "price": "100"},
                ],
                balances=[
                    {
                        "account": "crypto:phantom",
                        "instrument": "SOL",
                        "on_date": "2026-10-01",
                        "quantity": "2",
                    }
                ],
            )
        ]
    )
    key = instruments.crypto_key("SOL")
    with begin_immediate(finance.engine()) as conn:
        imp = conn.execute(text("SELECT id FROM imports LIMIT 1")).scalar_one()
        assets.add_holding(conn, account.id, "2026-10-02", key, Decimal(2), Decimal(0), "USD", imp)
    with finance.engine().connect() as conn:
        line = valuation.Positions(conn).lines(account.id, "2026-10-02")[0]
        engine = perf_lines.build(conn, "2026-10-02")
    assert line.value == 20_000
    assert engine is not None
    ln = engine.lines[f"{account.id}|{key}"]
    assert ln.value[engine.index("2026-10-02")] == 20_000


def _crypto_gain(finance: FinanceDomain, on: str) -> int:
    """Gain « Max » de la performance sur les lignes de cryptos (toutes leurs positions)."""
    with finance.engine().connect() as conn:
        eng = perf_lines.build(conn, on)
        crypto = set(conn.execute(text("SELECT id FROM accounts WHERE kind = 'crypto'")).scalars())
    assert eng is not None
    ids = [i for i, ln in eng.lines.items() if ln.kind == "position" and ln.account_id in crypto]
    return int(performance.report(eng, ids, None, None, "month")["summary"]["gain"]["minor"])


def test_performance_max_is_the_result_since_purchase(finance: FinanceDomain) -> None:
    # politique de calcul : un seul gain. La récompense est du gain (pas un apport), l'envoi
    # vers la Ledger garde son coût, la vente sort ce qu'elle a rapporté
    setup(finance)
    with finance.engine().connect() as conn:
        r = holdings.holdings(conn, "2026-10-27")["crypto"]["since_purchase"]
    assert r is not None
    assert _crypto_gain(finance, "2026-10-27") == minor(r["result"]) == -6_000


def test_a_send_outside_leaves_at_cost_and_a_late_price_keeps_the_gain(
    finance: FinanceDomain,
) -> None:
    # achat de 0.02 BTC pour 1 000 sans cours ce jour-là (le premier arrive le 5 mars) ; un
    # envoi de 0.01 vers un portefeuille non suivi sort au coût (500), pas au cours (800)
    add_ref(finance, "crypto:binance", "crypto", "Binance")
    finance.importer.process(
        [
            doc(
                prices=[btc("2026-03-05", "60000"), btc("2026-04-01", "80000")],
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
    with finance.engine().connect() as conn:
        r = crypto_cost.result(conn, "2026-10-27", valuation.Positions(conn))
    assert r is not None
    assert minor(r["sent_outside_cost"]) == 50_000
    # 0.01 BTC à 80 000 = 800, coût restant 500 : +300 ; l'envoi ne crée ni gain ni perte
    assert minor(r["result"]) == 30_000
    assert _crypto_gain(finance, "2026-10-27") == 30_000
