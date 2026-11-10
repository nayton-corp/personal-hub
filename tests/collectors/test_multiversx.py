"""Portefeuille MultiversX (EGLD) avec un faux transport : solde délégué compris, transferts
regroupés par transaction, frais, gaz rendu ignoré."""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from urllib.parse import urlsplit

import pytest

from hub.collectors.base import Failure
from hub.collectors.http import Http
from hub.collectors.market import flow as market
from tests.collectors.test_crypto_collectors import Fake, chain, dropped, held, query

ERD = "erd1qyu5wthldzr8wx5c9ucg8kjagg0jfs53s8nr3zpz3hypefsdd8ssycr6th"
PROVIDER = "erd1qqqqqqqqqqqqqqqpqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqhllllsajxzat"
BINANCE = "erd1sdslvlxvfnnflzj42l8czrcngq3xjjzkjp3rgul4ttk6hntr4qdsv6sets"
E18 = 10**18


def egld(n: str) -> str:
    return str(int(Decimal(n) * E18))


TRANSFERS = [
    {  # 2 EGLD délégués : ils restent à moi, seuls les frais sortent ; le gaz rendu ne compte pas
        "txHash": "T3",
        "type": "Transaction",
        "function": "delegate",
        "sender": ERD,
        "receiver": PROVIDER,
        "value": egld("2"),
        "fee": egld("0.0001"),
        "timestamp": 1775037600,  # 2026-04-01
    },
    {
        "txHash": "R3",
        "originalTxHash": "T3",
        "type": "SmartContractResult",
        "sender": PROVIDER,
        "receiver": ERD,
        "value": egld("0.00002"),
        "isRefund": True,
        "timestamp": 1775037606,
    },
    {  # récompenses réclamées : une transaction sans valeur et le versement du contrat
        "txHash": "R2",
        "originalTxHash": "T2",
        "type": "SmartContractResult",
        "sender": PROVIDER,
        "receiver": ERD,
        "value": egld("0.05"),
        "timestamp": 1772359206,
    },
    {
        "txHash": "T2",
        "type": "Transaction",
        "function": "claimRewards",
        "sender": ERD,
        "receiver": PROVIDER,
        "value": "0",
        "fee": egld("0.0002"),
        "timestamp": 1772359200,  # 2026-03-01
    },
    {  # 3 EGLD reçus de Binance
        "txHash": "T1",
        "type": "Transaction",
        "sender": BINANCE,
        "receiver": ERD,
        "value": egld("3"),
        "fee": egld("0.00005"),
        "timestamp": 1769940000,  # 2026-02-01
    },
]


def mvx_api(rows: list[dict[str, Any]] | None = None) -> Fake:
    inner = chain()
    listed = TRANSFERS if rows is None else rows

    def route(method: str, url: str, headers: dict[str, str], data: bytes | None) -> Any:
        if "multiversx" not in url:
            return inner.route(method, url, headers, data)
        path = urlsplit(url).path
        if path == f"/accounts/{ERD}":
            return 200, {"address": ERD, "balance": egld("1.5")}
        if path == f"/accounts/{ERD}/delegation":
            return 200, [
                {
                    "userActiveStake": egld("2"),
                    "claimableRewards": egld("0.01"),
                    "userUnBondable": "0",
                    "userUndelegatedList": [{"amount": egld("0.25")}],
                }
            ]
        if path == f"/accounts/{ERD}/transfers":
            start, size = int(query(url)["from"]), int(query(url)["size"])
            return 200, listed[start : start + size]
        raise AssertionError(url)

    return Fake(route)


def test_a_multiversx_wallet_reads_its_delegation_and_history(make_env: Any) -> None:
    wallet = {"account": "crypto:multiversx", "asset": "EGLD", "addresses": [ERD]}
    env = make_env("market", creds={"wallets": [wallet]}, market={"coingecko_pause_seconds": 0})
    assert market.run(env, "run", Http(mvx_api())).detail is None
    (doc,) = dropped(env)
    # disponible, délégué, récompenses à réclamer, en cours de retrait
    assert held(doc) == [("crypto:multiversx", "CRYPTO:EGLD", Decimal("3.76"))]
    got = [(t.on_date, t.txid, t.quantity, t.fee, t.stake) for t in doc.transactions]
    assert got == [
        ("2026-02-01", "T1", Decimal(3), Decimal(0), False),
        # la récompense réclamée : une arrivée de staking, nette des frais
        ("2026-03-01", "T2", Decimal("0.0498"), Decimal("0.0002"), True),
        ("2026-04-01", "T3", Decimal("-0.0001"), Decimal("0.0001"), False),
    ]
    assert env.memory.get("chain_txs") == ["crypto:multiversx@multiversx"]
    # ensuite : la page la plus récente seulement
    later = mvx_api()
    market.run(env, "run", Http(later))
    pages = [query(u)["from"] for _m, u, _h in later.calls if "/transfers" in u]
    assert pages == ["0"]


def test_a_long_multiversx_history_is_flagged(make_env: Any) -> None:
    rows = [{**TRANSFERS[-1], "txHash": f"T{i}"} for i in range(2000)]
    wallet = {"account": "crypto:multiversx", "asset": "EGLD", "addresses": [ERD]}
    env = make_env("market", creds={"wallets": [wallet]}, market={"coingecko_pause_seconds": 0})
    result = market.run(env, "run", Http(mvx_api(rows)))
    assert result.detail == "partial history.multiversx.multiversx:truncated"
    assert not env.memory.get("chain_txs")


def test_a_multiversx_address_is_checked(make_env: Any) -> None:
    wallet = {"account": "crypto:x", "asset": "EGLD", "addresses": ["erd1bad"]}
    with pytest.raises(Failure) as err:
        market.wallet_entries(make_env("market", creds={"wallets": [wallet]}))
    assert err.value.outcome == "auth_error"
