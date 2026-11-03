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
    crypto_moves,
    crypto_pairing,
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


def validate_links(finance: FinanceDomain, on: str = "2026-10-27") -> list[str]:
    """Ce que les cartes `link_crypto_moves` demandées par le hub écrivent une fois validées
    (le vrai chemin, par le Double Sas, est testé dans test_double_sas.py)."""
    with begin_immediate(finance.engine()) as conn:
        found = crypto_pairing.candidates(crypto_moves.moves(conn, on))
        for c in found:
            method = "claim" if c.kind == "stake" else "window"
            crypto_moves.link(conn, c.entry_seq, c.kind, c.peer_seq, method, actor="test")
    return [c.kind for c in found]


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
    assert crypto_moves.role("EXCHANGE/TRADE/BUY") == "trade"
    assert crypto_moves.role("SWISSBORG/INCOME/YIELD") == "income"
    assert crypto_moves.role("CRYPTO/FEE") == "fee"
    assert crypto_moves.role("CRYPTO/RECEIVE") == "in"
    assert crypto_moves.role("SWISSBORG/WITHDRAWAL") == "out"
    assert crypto_moves.role("OPENING") is None


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


def test_a_staking_exit_keeps_the_cost_and_the_reward_is_a_gain(finance: FinanceDomain) -> None:
    """Mise chez un staking lue comme un envoi (parts brûlées, sans marque), puis le claim
    marqué : les deux restent à moi, le coût ne bouge pas, rien n'est sorti ni arrivé."""
    from hub.domains.finance.patrimoine.app import reconcile

    add_ref(finance, "crypto:binance", "crypto", "Binance")
    add_ref(finance, "crypto:ledger", "crypto", "Ledger")

    def tx(txid: str, on: str, q: str, **kw: str) -> dict[str, str]:
        row = {"account": "crypto:ledger", "instrument": "BTC", "on_date": on, "txid": txid}
        return {**row, "quantity": q, "fee": "0", **kw}

    out = ("BTC", "-0.02", "withdrawal")

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
                    op("out:1", "withdrawal", "2026-03-03", out, txid="t1"),
                ],
            )
        ]
    )
    finance.importer.process([doc(transactions=[tx("t1", "2026-03-03", "0.02")])])
    finance.importer.process([doc(transactions=[tx("t2", "2026-08-01", "-0.01")])])
    claim = tx("t3", "2026-09-01", "0.011", kind="stake")
    finance.importer.process([doc(transactions=[claim])])
    # tant que la carte attend, l'envoi est sorti de mes comptes : rien n'est deviné à la lecture
    with finance.engine().connect() as conn:
        pending = crypto_cost.result(conn, "2026-10-27", valuation.Positions(conn))
        waiting = reconcile.report(conn, "2026-10-27")
    assert pending is not None
    assert (minor(pending["cost"]), minor(pending["sent_outside_cost"])) == (50_000, 50_000)
    assert [b.kind for b in waiting.breaks if b.kind == "sent_outside"] == ["sent_outside"]
    assert validate_links(finance) == ["stake"]
    with finance.engine().connect() as conn:
        r = crypto_cost.result(conn, "2026-10-27", valuation.Positions(conn))
        found = reconcile.report(conn, "2026-10-27")
    assert r is not None
    # 0.021 BTC à 40 000 = 840 pour 1 000 payés ; la récompense (0.001) entre sans coût
    assert (minor(r["value"]), minor(r["cost"]), minor(r["result"])) == (84_000, 100_000, -16_000)
    assert minor(r["sent_outside_cost"]) == 0
    assert minor(r["arrived_from_outside"]) == 0
    assert not [b for b in found.breaks if b.kind in ("sent_outside", "arrived_outside")]


def test_a_transaction_read_again_with_another_net_gets_a_correction(
    finance: FinanceDomain,
) -> None:
    """Une lecture fausse (claim annulé par une trace fantôme) puis corrigée : le mouvement de
    parts n'est pas réécrit, une ligne de correction apporte la différence."""
    add_ref(finance, "crypto:ledger", "crypto", "Ledger")

    def read(q: str) -> None:
        row = {"account": "crypto:ledger", "instrument": "BTC", "on_date": "2026-09-01"}
        tx = {**row, "txid": "t9", "quantity": q, "fee": "0", "kind": "stake"}
        finance.importer.process([doc(prices=[btc("2026-09-01", "40000")], transactions=[tx])])

    read("0.001")
    read("0.011")
    read("0.011")  # relu tel quel : rien de plus
    with finance.engine().connect() as conn:
        rows = conn.execute(text("SELECT quantity, amount_minor FROM trades")).all()
    assert sorted((Decimal(q), a) for q, a in rows) == [
        (Decimal("0.001"), 4_000),
        (Decimal("0.01"), 40_000),
    ]


def test_a_transfer_with_withdrawal_fees_stays_between_my_accounts(
    finance: FinanceDomain,
) -> None:
    """Un retrait Binance de 0.01 BTC arrive à 0.0098 sur la Ledger, sans txid commun : c'est un
    virement entre mes comptes, les 0.0002 perdus sont des frais, rien n'est sorti ni arrivé."""
    from hub.domains.finance.patrimoine.app import reconcile

    add_ref(finance, "crypto:binance", "crypto", "Binance")
    add_ref(finance, "crypto:ledger", "crypto", "Ledger")
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
    row = {"account": "crypto:ledger", "instrument": "BTC", "on_date": "2026-04-02"}
    finance.importer.process([doc(transactions=[{**row, "txid": "t1", "quantity": "0.0098"}])])
    # sans lien, l'envoi sort à son coût et l'arrivée entre au cours du jour
    with finance.engine().connect() as conn:
        pending = crypto_cost.result(conn, "2026-10-27", valuation.Positions(conn))
    assert pending is not None
    assert minor(pending["sent_outside_cost"]) == 50_000
    assert minor(pending["arrived_from_outside"]) == 49_000  # 0.0098 à 50 000
    assert validate_links(finance) == ["transfer"]
    with finance.engine().connect() as conn:
        r = crypto_cost.result(conn, "2026-10-27", valuation.Positions(conn))
        found = reconcile.report(conn, "2026-10-27")
    assert r is not None
    assert minor(r["cost"]) == 100_000  # le coût suit les parts, frais compris
    assert minor(r["sent_outside_cost"]) == 0
    assert minor(r["arrived_from_outside"]) == 0
    assert not [b for b in found.breaks if b.kind in ("sent_outside", "arrived_outside")]
