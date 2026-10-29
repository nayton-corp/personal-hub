"""Historique d'une plateforme crypto (Binance) au registre, et mouvements reliés entre mes
comptes crypto (Ledger ↔ Binance) par le txId, sinon la quantité."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import pytest

from hub.domains.finance import catalog, links, market, transfers
from hub.domains.finance.domain import FinanceDomain
from hub.domains.finance.importer import Incoming
from hub.platform.db import begin_immediate
from tests.finance.conftest import rows


def op(op_id: str, kind: str, on: str, *legs: tuple[str, str, str], **extra: str) -> dict[str, Any]:
    return {
        "account": "crypto:binance",
        "id": op_id,
        "kind": kind,
        "on_date": on,
        "legs": [{"instrument": a, "quantity": q, "role": r} for a, q, r in legs],
        **extra,
    }


def price(symbol: str, value: str, currency: str = "CHF") -> dict[str, str]:
    return {
        "instrument": symbol,
        "kind": "crypto",
        "on_date": "2026-03-01",
        "price": value,
        "currency": currency,
        "source": "binance",
    }


BINANCE = {
    "format": market.FORMAT,
    "fetched_at": "2026-10-27",
    "fx": [
        {"on_date": "2026-03-01", "base": "USD", "quote": "CHF", "rate": "0.8", "source": "ecb"}
    ],
    "prices": [price("BTC", "50000"), price("BNB", "500")],
    "operations": [
        op(
            "fiat:f1",
            "fiat_deposit",
            "2026-03-01",
            ("CHF", "1000", "deposit"),
            ("CHF", "-1", "fee"),
        ),
        op(
            "payment:p1",
            "card_buy",
            "2026-03-02",
            ("CHF", "102", "deposit"),
            ("CHF", "-100", "trade"),
            ("CHF", "-2", "fee"),
            ("USDT", "100", "trade"),
        ),
        op(
            "trade:BTCUSDT:9:100",
            "trade",
            "2026-03-03",
            ("BTC", "0.001", "trade"),
            ("USDT", "-60", "trade"),
            ("BNB", "-0.00008", "fee"),
        ),
        op("deposit:d1", "deposit", "2026-03-05", ("BTC", "0.01", "deposit"), txid="aa11"),
        # même quantité, même jour, autre transaction : pas l'envoi vers la Ledger
        op(
            "withdraw:w0",
            "withdrawal",
            "2026-04-01",
            ("BTC", "-0.005", "withdrawal"),
            ("BTC", "-0.0001", "fee"),
            txid="cc33",
        ),
        op(
            "withdraw:w1",
            "withdrawal",
            "2026-04-01",
            ("BTC", "-0.005", "withdrawal"),
            ("BTC", "-0.0001", "fee"),
            txid="0xBB22",
        ),
        op("reward:flexible:USDT:2026-04-02", "reward", "2026-04-02", ("USDT", "0.5", "income")),
        op("dust:45", "dust", "2026-04-07", ("XRP", "-0.5", "trade"), ("BNB", "0.0002", "trade")),
        op("dividend:9", "distribution", "2026-04-08", ("XRP", "1", "income")),
    ],
}
LEDGER = {
    "format": market.FORMAT,
    "fetched_at": "2026-10-27",
    "transactions": [
        # envoyé vers Binance la veille de l'arrivée, déjà au registre : sa valeur
        {
            "account": "crypto:ledger",
            "instrument": "BTC",
            "on_date": "2026-03-04",
            "txid": "aa11",
            "quantity": "-0.0101",
            "fee": "0.0001",
        },
        {
            "account": "crypto:ledger",
            "instrument": "BTC",
            "on_date": "2026-04-02",
            "txid": "bb22",
            "quantity": "0.005",
            "fee": "0",
        },
    ],
}


@pytest.fixture
def accounts(finance: FinanceDomain) -> None:
    with begin_immediate(finance.engine()) as conn:
        for ref, name in [("crypto:binance", "Binance"), ("crypto:ledger", "Ledger")]:
            catalog.add_account(
                conn, institution=name, name=name, kind="crypto", external_ref=ref, currency="CHF"
            )


def journal(finance: FinanceDomain, ref: str) -> list[tuple[Any, ...]]:
    return rows(
        finance,
        "SELECT e.bank_ref, e.bank_tx_code, e.amount_minor, e.remittance, vc.category_id "
        "FROM entries e JOIN accounts a ON a.id = e.account_id "
        "LEFT JOIN v_entry_category vc ON vc.entry_seq = e.seq "
        "WHERE a.external_ref = :r AND e.kind = 'movement' ORDER BY e.seq",
        r=ref,
    )


def test_binance_operations_land_in_the_journal(finance: FinanceDomain, accounts: None) -> None:
    report = finance.importer.process([Incoming("binance.json", json.dumps(BINANCE).encode())])
    statuses = {s.index: (s.status, tuple(sorted(s.reasons))) for s in report.statements}
    assert statuses.pop(9) == ("needs_review", ("missing_price",))  # XRP sans cours : attend
    assert set(statuses.values()) == {("applied", ())}
    assert journal(finance, "crypto:binance") == [
        ("fiat:f1", "EXCHANGE/DEPOSIT", 100_000, "1000 CHF", "transfer-own"),
        ("fiat:f1", "EXCHANGE/FEE", -100, "-1 CHF", "frais-placement"),
        ("payment:p1", "EXCHANGE/DEPOSIT", 10_200, "102 CHF", "transfer-own"),
        ("payment:p1", "EXCHANGE/TRADE/SELL", -10_000, "-100 CHF", "transfer-titres"),
        ("payment:p1", "EXCHANGE/FEE", -200, "-2 CHF", "frais-placement"),
        # les deux côtés d'un échange à la valeur du plus sûr : la monnaie, puis le stablecoin
        ("payment:p1", "EXCHANGE/TRADE/BUY", 10_000, "100 USDT", "transfer-titres"),
        ("trade:BTCUSDT:9:100", "EXCHANGE/TRADE/BUY", 4_800, "0.001 BTC", "transfer-titres"),
        ("trade:BTCUSDT:9:100", "EXCHANGE/TRADE/SELL", -4_800, "-60 USDT", "transfer-titres"),
        ("trade:BTCUSDT:9:100", "EXCHANGE/FEE", -4, "-0.00008 BNB", "frais-placement"),
        ("deposit:d1", "EXCHANGE/DEPOSIT", 50_000, "0.01 BTC", "transfer-own"),
        ("withdraw:w0", "EXCHANGE/WITHDRAWAL", -25_000, "-0.005 BTC", "transfer-own"),
        ("withdraw:w0", "EXCHANGE/FEE", -500, "-0.0001 BTC", "frais-placement"),
        ("withdraw:w1", "EXCHANGE/WITHDRAWAL", -25_000, "-0.005 BTC", "transfer-own"),
        ("withdraw:w1", "EXCHANGE/FEE", -500, "-0.0001 BTC", "frais-placement"),
        ("reward:flexible:USDT:2026-04-02", "EXCHANGE/INCOME", 40, "0.5 USDT", "rendement"),
        # sans cours, un actif échangé prend la valeur de ce qu'il a donné
        ("dust:45", "EXCHANGE/TRADE/SELL", -10, "-0.5 XRP", "transfer-titres"),
        ("dust:45", "EXCHANGE/TRADE/BUY", 10, "0.0002 BNB", "transfer-titres"),
    ]
    labels = rows(
        finance,
        "SELECT DISTINCT label, counterparty FROM entries WHERE bank_tx_code = 'EXCHANGE/INCOME'",
    )
    assert labels == [("Récompense Earn USDT", "Binance")]
    # mouvements de parts : pas pour le franc
    trades = rows(finance, "SELECT isin, quantity, amount_minor FROM trades ORDER BY seq")
    assert ("CRYPTO:USDT", "100", 10_000) in trades
    assert ("CRYPTO:BTC", "0.001", 4_800) in trades
    assert all(not isin.endswith(":CHF") for isin, *_x in trades)
    # le même fichier redéposé est un doublon
    again = finance.importer.process([Incoming("copie.json", json.dumps(BINANCE).encode())])
    assert [f.status for f in again.files] == ["duplicate"]


def test_wallet_and_platform_movements_are_linked(finance: FinanceDomain, accounts: None) -> None:
    finance.importer.process([Incoming("binance.json", json.dumps(BINANCE).encode())])
    finance.importer.process([Incoming("market.json", json.dumps(LEDGER).encode())])
    assert journal(finance, "crypto:ledger") == [
        # l'arrivée sur Binance était déjà là : l'envoi prend sa valeur, les frais à part
        ("aa11", "CRYPTO/SEND", -50_000, "-0.01 BTC", "transfer-own"),
        ("aa11", "CRYPTO/FEE", -500, "-0.0001 BTC", "frais-placement"),
        # le retrait du même txId, pas l'autre de même quantité
        ("bb22", "CRYPTO/RECEIVE", 25_000, "0.005 BTC", "transfer-own"),
    ]
    with begin_immediate(finance.engine()) as conn:
        transfers.refresh(conn)
    paired = rows(
        finance,
        "SELECT d.bank_ref, c.bank_ref FROM transfer_links t "
        "JOIN entries d ON d.seq = t.debit_seq JOIN entries c ON c.seq = t.credit_seq "
        "ORDER BY d.seq",
    )
    assert paired == [("withdraw:w1", "bb22"), ("aa11", "deposit:d1")]


def test_counterpart_prefers_the_txid_and_skips_taken_sides(
    finance: FinanceDomain, accounts: None
) -> None:
    finance.importer.process([Incoming("binance.json", json.dumps(BINANCE).encode())])
    with finance.engine().connect() as conn:
        found = links.counterpart(conn, "crypto:ledger", "BTC", "2026-04-02", Decimal("0.005"))
        by_txid = links.counterpart(
            conn, "crypto:ledger", "BTC", "2026-04-02", Decimal("0.005"), "bb22"
        )
        none = links.counterpart(
            conn, "crypto:ledger", "BTC", "2026-04-20", Decimal("0.005"), "bb22"
        )
    seqs = dict(
        rows(
            finance, "SELECT bank_ref, seq FROM entries WHERE bank_tx_code = 'EXCHANGE/WITHDRAWAL'"
        )
    )
    assert found == (seqs["withdraw:w0"], -25_000)  # sans txId : la première de même quantité
    assert by_txid == (seqs["withdraw:w1"], -25_000)
    assert none is None  # hors délai


def test_a_value_given_by_the_platform_wins(finance: FinanceDomain, accounts: None) -> None:
    doc = {
        "format": market.FORMAT,
        "fetched_at": "2026-10-27",
        "fx": BINANCE["fx"],
        "prices": [price("BTC", "50000")],
        "operations": [
            {
                **op("tx:c1", "reward", "2026-03-01", ("BTC", "0.001", "income")),
                # Coinbase donne la valeur reçue : 60 USD, pas le cours du jour (50 CHF)
                "legs": [
                    {
                        "instrument": "BTC",
                        "quantity": "0.001",
                        "role": "income",
                        "value": "60",
                        "value_currency": "USD",
                    }
                ],
            }
        ],
    }
    finance.importer.process([Incoming("coinbase.json", json.dumps(doc).encode())])
    assert journal(finance, "crypto:binance") == [
        ("tx:c1", "EXCHANGE/INCOME", 4_800, "0.001 BTC", "rendement"),
    ]


def test_a_token_and_its_gas_share_a_txid(finance: FinanceDomain, accounts: None) -> None:
    doc = {
        "format": market.FORMAT,
        "fetched_at": "2026-10-27",
        "fx": BINANCE["fx"],
        "prices": [price("ETH", "2000")],
        "transactions": [
            {
                "account": "crypto:ledger",
                "instrument": "ETH",
                "on_date": "2026-03-01",
                "txid": "0xabc",
                "quantity": "-0.002",
                "fee": "0.001",
            },
            {
                "account": "crypto:ledger",
                "instrument": "USDT",
                "on_date": "2026-03-01",
                "txid": "0xabc",
                "quantity": "-50",
                "fee": "0",
            },
        ],
    }
    finance.importer.process([Incoming("market.json", json.dumps(doc).encode())])
    got = journal(finance, "crypto:ledger")
    # deux écritures distinctes pour la même transaction ; le stablecoin vaut 1 USD
    assert ("0xabc", "CRYPTO/SEND", -4_000, "-50 USDT", "transfer-own") in got
    assert sum(1 for r in got if r[0] == "0xabc") == 3
