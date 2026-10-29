"""Portefeuilles crypto (xpub, Ethereum et ses jetons, Solana) et plateformes (Binance, KuCoin,
Coinbase) avec un faux transport : adresses dérivées, signatures, soldes lus par Finance."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

from hub.collectors.base import Failure
from hub.collectors.exchanges import binance, coinbase, kucoin
from hub.collectors.http import Http
from hub.collectors.market import flow as market
from hub.collectors.runtime import Env
from hub.domains.finance import market as finance_market

Route = Callable[[str, str, dict[str, str], bytes | None], tuple[int, Any]]

# vecteurs de BIP84 (phrase « abandon … about ») : clé publique du compte m/84'/0'/0'
ZPUB = (
    "zpub6rFR7y4Q2AijBEqTUquhVz398htDFrtymD9xYYfG1m4wAcvPhXNfE3EfH1r1ADqtfSdVCToUG868RvUUkgDKf31"
    "mGDtKsAYz2oz2AGutZYs"
)
XPUB = (
    "xpub6CatWdiZiodmUeTDp8LT5or8nmbKNcuyvz7WyksVFkKB4RHwCD3XyuvPEbvqAQY3rAPshWcMLoP2fMFMKHPJ4ZeZXY"
    "VUhLv1VMrjPC7PW6V"
)
XPRV = (  # vecteur 1 de BIP32, clé maîtresse privée
    "xprv9s21ZrQH143K3QTDL4LXw2F7HEK3wJUD2nW2nRk4stbPy6cq3jPPqjiChkVvvNKmPGJxWUtg6LnF5kejMRNNU3TG"
    "tRBeJgk33yuGBxrMPHi"
)
RECEIVE_0 = "bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyu"  # m/84'/0'/0'/0/0
CHANGE_0 = "bc1q8c6fshw2dlwun7ekn9qwf37cu2rn755upcp6el"  # m/84'/0'/0'/1/0
USDC_ETH = "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"
USDC_SOL = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"


class Fake:
    def __init__(self, route: Route) -> None:
        self.route = route
        self.calls: list[tuple[str, str, dict[str, str]]] = []

    def __call__(
        self, method: str, url: str, headers: dict[str, str], data: bytes | None
    ) -> tuple[int, bytes]:
        self.calls.append((method, url, headers))
        status, body = self.route(method, url, headers, data)
        return status, body if isinstance(body, bytes) else json.dumps(body).encode()


def dropped(env: Env) -> list[finance_market.MarketFile]:
    files = sorted(p for p in env.inbox_root.glob("*") if p.is_file())
    return [finance_market.parse(p.read_bytes()) for p in files]


def held(doc: finance_market.MarketFile) -> list[tuple[str, str, Decimal]]:
    return [(b.account, b.key, b.quantity) for b in doc.balances]


# --- portefeuilles -------------------------------------------------------------------------------


def chain(
    btc: dict[str, int] | None = None,
    broken: str | None = None,
    *,
    sol_owner: str = "Sol1",
    eth_txs: dict[str, list[dict[str, Any]]] | None = None,
    sol_txs: dict[str, dict[str, Any]] | None = None,
) -> Fake:
    """mempool (satoshis par adresse utilisée), nœud Ethereum, RPC Solana, prix et change,
    historiques Blockscout (`eth_txs` : action → lignes) et Solana (`sol_txs` : signature →
    transaction)."""
    btc = btc or {}

    def route(method: str, url: str, headers: dict[str, str], data: bytes | None) -> Any:
        if broken and broken in url:
            return 503, b""
        if "frankfurter" in url:
            return 200, {"rates": {}}
        if "coingecko" in url:
            return 200, {"prices": []}
        if "/txs/chain" in url:
            return 200, []  # pas d'historique
        if "etherscan" in url:  # Routescan (Ethereum) ou Etherscan V2 (autres réseaux)
            q = query(url)
            rows = (eth_txs or {}).get(q["action"], []) if q["page"] == "1" else []
            if not rows:
                return 200, {"status": "0", "message": "No transactions found", "result": []}
            return 200, {"status": "1", "message": "OK", "result": rows}
        if "binance" in url:
            return 200, []
        if "mempool" in url:
            sats = btc.get(url.rsplit("/", 1)[1])
            stats = {
                "funded_txo_sum": sats or 0,
                "spent_txo_sum": 0,
                "tx_count": int(sats is not None),
            }
            return 200, {"chain_stats": stats, "mempool_stats": {"tx_count": 0}}
        rpc = json.loads(data or b"{}")
        params = rpc.get("params")
        if rpc.get("method") == "eth_getBalance":
            return 200, {"result": hex(5 * 10**17)}
        if rpc.get("method") == "eth_call":
            to, call = params[0]["to"], params[0]["data"]
            if call == "0x313ce567":
                return 200, {"result": hex(6)}
            return 200, {"result": hex(1_234_560_000 if to == USDC_ETH else 0)}
        if rpc.get("method") == "getBalance":
            assert params == [sol_owner]
            return 200, {"result": {"value": 2_500_000_000}}
        if rpc.get("method") == "getSignaturesForAddress":
            sigs = [{"signature": k} for k in (sol_txs or {})]
            return 200, {"result": sigs}
        if rpc.get("method") == "getTransaction":
            return 200, {"result": (sol_txs or {})[params[0]]}
        if rpc.get("method") == "getTokenAccountsByOwner":
            items = [
                {"mint": USDC_SOL, "tokenAmount": {"amount": "7500000", "decimals": 6}},
                {"mint": "Spam111", "tokenAmount": {"amount": "999", "decimals": 0}},
            ]
            value = [{"account": {"data": {"parsed": {"info": i}}}} for i in items]
            return 200, {"result": {"value": value}}
        raise AssertionError(url)

    return Fake(route)


def mempool_calls(fake: Fake) -> list[str]:
    return [u.rsplit("/", 1)[1] for _m, u, _h in fake.calls if "mempool" in u and "/txs/" not in u]


def test_xpub_walks_receive_and_change_until_the_gap(make_env: Any) -> None:
    creds = {"wallets": [{"account": "crypto:ledger", "asset": "BTC", "xpub": ZPUB}]}
    env = make_env("market", creds=creds, market={"gap_limit": 3})
    fake = chain({RECEIVE_0: 100_000_000, CHANGE_0: 25_000_000})
    assert market.run(env, "run", Http(fake)).outcome == "ok"
    (doc,) = dropped(env)
    assert held(doc) == [("crypto:ledger", "CRYPTO:BTC", Decimal("1.25"))]
    calls = mempool_calls(fake)
    # BIP84 seulement (zpub) : 0/0 utilisée puis 3 vides, 1/0 utilisée puis 3 vides
    assert len(calls) == 8
    assert (calls[0], calls[4]) == (RECEIVE_0, CHANGE_0)


def test_plain_xpub_tries_every_script_and_skips_unused_ones(make_env: Any) -> None:
    creds = {"wallets": [{"account": "crypto:ledger", "asset": "BTC", "xpub": XPUB}]}
    env = make_env("market", creds=creds, market={"gap_limit": 2})
    fake = chain({RECEIVE_0: 50_000_000})
    market.run(env, "run", Http(fake))
    calls = mempool_calls(fake)
    # wpkh : 0/0 utilisée, 0/1-0/2 vides, 1/0-1/1 vides ; sh-wpkh, pkh, tr : 2 réceptions vides
    assert len(calls) == 5 + 3 * 2
    assert [c[:1] for c in calls[5:9]] == ["3", "3", "1", "1"]
    assert all(c.startswith("bc1p") for c in calls[9:])
    assert held(dropped(env)[0]) == [("crypto:ledger", "CRYPTO:BTC", Decimal("0.5"))]
    chosen = {"wallets": [{"account": "crypto:l", "asset": "BTC", "xpub": XPUB, "script": "wpkh"}]}
    only = chain({RECEIVE_0: 1})
    market.run(make_env("market", creds=chosen, market={"gap_limit": 2}), "run", Http(only))
    assert len(mempool_calls(only)) == 5


@pytest.mark.parametrize(
    "wallet",
    [
        {"asset": "BTC", "xpub": XPRV},
        {"asset": "BTC", "xpub": XPRV, "script": "wpkh"},  # clé privée : refusée même ainsi
        {"asset": "BTC", "xpub": "xpub-mal-formee", "script": "wpkh"},
        {"asset": "BTC", "xpub": XPUB, "script": "p2sh-multisig"},
        {"asset": "ETH", "addresses": ["pas-une-adresse"]},
        {"asset": "ETH", "xpub": XPUB},
        {"asset": "DOGE", "addresses": ["D1"]},
        {"asset": "SOL", "addresses": []},
    ],
)
def test_wallet_secrets_are_checked_before_any_call(make_env: Any, wallet: dict[str, Any]) -> None:
    creds = {"wallets": [{"account": "crypto:x", **wallet}]}
    fake = chain()
    with pytest.raises(Failure) as exc:
        market.run(make_env("market", creds=creds), "run", Http(fake))
    assert (exc.value.outcome, exc.value.detail) == ("auth_error", "secret:wallets")
    assert not [u for _m, u, _h in fake.calls if "mempool" in u or "rpc" in u]


def test_eth_and_sol_wallets_read_native_coins_and_known_tokens(make_env: Any) -> None:
    eth = "0x" + "ab" * 20
    creds = {
        "wallets": [
            {"account": "crypto:metamask", "asset": "ETH", "addresses": [eth]},
            {"account": "crypto:trust", "asset": "SOL", "addresses": ["Sol1"]},
            {"account": "crypto:trust", "asset": "ETH", "addresses": [eth]},
        ]
    }
    env = make_env("market", creds=creds)
    fake = chain()
    assert market.run(env, "run", Http(fake)).detail is None
    assert held(dropped(env)[0]) == [
        ("crypto:metamask", "CRYPTO:ETH", Decimal("0.5")),
        ("crypto:metamask", "CRYPTO:USDC", Decimal("1234.56")),
        # un compte, deux chaînes : SOL et ETH additionnés, l'USDC des deux aussi
        ("crypto:trust", "CRYPTO:ETH", Decimal("0.5")),
        ("crypto:trust", "CRYPTO:SOL", Decimal("2.5")),
        ("crypto:trust", "CRYPTO:USDC", Decimal("1242.06")),
    ]


ETH_ME = "0x" + "ab" * 20


def test_eth_and_sol_wallets_read_their_history(make_env: Any) -> None:
    """Règle du hub : un portefeuille ETH ou SOL amène aussi ses transactions au Journal."""
    other = "0x" + "cd" * 20
    eth_txs = {
        "txlist": [  # un envoi de 0.2 ETH (gaz : 21 000 × 10 gwei), une réception
            {
                "hash": "0xs1",
                "from": ETH_ME,
                "to": other,
                "value": str(2 * 10**17),
                "gasUsed": "21000",
                "gasPrice": str(10**10),
                "isError": "0",
                "timeStamp": "1772366400",
            },
            {
                "hash": "0xr1",
                "from": other,
                "to": ETH_ME,
                "value": str(10**18),
                "gasUsed": "21000",
                "gasPrice": str(10**10),
                "isError": "0",
                "timeStamp": "1772280000",
            },
        ],
        "tokentx": [
            {
                "hash": "0xt1",
                "from": other,
                "to": ETH_ME,
                "value": "5000000",
                "tokenDecimal": "6",
                "contractAddress": USDC_ETH.lower(),
                "timeStamp": "1772452800",
            },
            {
                "hash": "0xspam",
                "from": other,
                "to": ETH_ME,
                "value": "1",
                "tokenDecimal": "0",
                "contractAddress": "0x" + "ee" * 20,
                "timeStamp": "1772452800",
            },
        ],
    }
    sol_txs = {
        "SigA": {
            "blockTime": 1772539200,
            "meta": {
                "fee": 5000,
                "preBalances": [3_000_005_000, 0],
                "postBalances": [2_000_000_000, 1_000_000_000],
                "preTokenBalances": [],
                "postTokenBalances": [],
            },
            "transaction": {"message": {"accountKeys": [{"pubkey": "Sol1"}, {"pubkey": "X"}]}},
        },
        "SigB": {
            "blockTime": 1772625600,
            "meta": {
                "fee": 5000,
                "preBalances": [10, 5],
                "postBalances": [5, 5],
                "preTokenBalances": [
                    {
                        "mint": USDC_SOL,
                        "owner": "Sol1",
                        "uiTokenAmount": {"amount": "1000000", "decimals": 6},
                    }
                ],
                "postTokenBalances": [
                    {
                        "mint": USDC_SOL,
                        "owner": "Sol1",
                        "uiTokenAmount": {"amount": "3000000", "decimals": 6},
                    }
                ],
            },
            "transaction": {"message": {"accountKeys": [{"pubkey": "Y"}, {"pubkey": "Sol1"}]}},
        },
    }
    creds = {
        "wallets": [
            {"account": "crypto:metamask", "asset": "ETH", "addresses": [ETH_ME]},
            {"account": "crypto:phantom", "asset": "SOL", "addresses": ["Sol1"]},
        ]
    }
    env = make_env("market", creds=creds)
    result = market.run(env, "run", Http(chain(eth_txs=eth_txs, sol_txs=sol_txs)))
    assert result.detail is None
    (doc,) = dropped(env)
    got = [(t.account, t.on_date, t.txid, t.symbol, t.quantity, t.fee) for t in doc.transactions]
    assert got == [
        ("crypto:metamask", "2026-02-28", "0xr1", "ETH", Decimal(1), Decimal(0)),
        # envoyé 0.2 et 0.00021 de gaz : le net compte les frais
        ("crypto:metamask", "2026-03-01", "0xs1", "ETH", Decimal("-0.20021"), Decimal("0.00021")),
        ("crypto:metamask", "2026-03-02", "0xt1", "USDC", Decimal(5), Decimal(0)),
        ("crypto:phantom", "2026-03-03", "SigA", "SOL", Decimal("-1.000005"), Decimal("0.000005")),
        ("crypto:phantom", "2026-03-04", "SigB", "USDC", Decimal(2), Decimal(0)),
    ]
    assert env.memory.get("chain_txs") == ["crypto:metamask", "crypto:phantom@solana"]


KILN = "0x30a4aa1d14D44f0f5BFe887447AB6FAcc94A549F"
WETH_POLYGON = "0x7ceB23fD6bC0adD59E62ac25578270cFf1b9f619"


def test_an_eth_wallet_reads_its_networks_and_staking(make_env: Any) -> None:
    """Coinbase Wallet : ETH staké chez Kiln (cbwsETH), et des fonds sur Base et Polygon."""
    base = chain()

    def route(method: str, url: str, headers: dict[str, str], data: bytes | None) -> Any:
        rpc = json.loads(data or b"{}")
        if rpc.get("method") == "eth_getBalance":
            wei = {"base": 5 * 10**16, "polygon": 3 * 10**18}
            return 200, {"result": hex(next((v for k, v in wei.items() if k in url), 0))}
        if rpc.get("method") == "eth_call":
            to, call = rpc["params"][0]["to"], rpc["params"][0]["data"]
            if to == KILN and call.startswith("0x70a08231"):
                return 200, {"result": hex(488_379 * 10**12)}  # 0.488379 parts
            if to == KILN and call.startswith("0x3af9e669"):
                return 200, {"result": hex(512 * 10**15)}  # 0.512 ETH avec les récompenses
            if to == WETH_POLYGON:
                return 200, {"result": hex(31 * 10**15 if call != "0x313ce567" else 18)}
        if "chainid=8453" in url and query(url)["action"] == "txlist":
            row = {
                "hash": "0xb1",
                "from": "0x" + "cd" * 20,
                "to": ETH_ME,
                "value": str(5 * 10**16),
                "gasUsed": "1",
                "gasPrice": "1",
                "isError": "0",
                "timeStamp": "1772280000",
            }
            return 200, {"status": "1", "message": "OK", "result": [row]}
        if "routescan" in url and query(url)["action"] == "tokentx":
            row = {  # parts reçues au staking
                "hash": "0xk1",
                "from": "0x" + "00" * 20,
                "to": ETH_ME,
                "value": str(488_379 * 10**12),
                "tokenDecimal": "18",
                "contractAddress": KILN.lower(),
                "timeStamp": "1772366400",
            }
            return 200, {"status": "1", "message": "OK", "result": [row]}
        return base.route(method, url, headers, data)

    wallet = {
        "account": "crypto:coinbase-wallet",
        "asset": "ETH",
        "addresses": [ETH_ME],
        "networks": ["ethereum", "base", "polygon"],
    }
    creds = {"wallets": [wallet], "etherscan_key": "cle-gratuite"}
    env = make_env("market", creds=creds, market={"erc20_tokens": {}})
    fake = Fake(route)
    assert market.run(env, "run", Http(fake)).detail is None
    (doc,) = dropped(env)
    assert held(doc) == [
        # 0.05 sur Base, 0.031 de WETH sur Polygon, 0.512 mis en jeu chez Kiln
        ("crypto:coinbase-wallet", "CRYPTO:ETH", Decimal("0.593")),
        ("crypto:coinbase-wallet", "CRYPTO:POL", Decimal(3)),
    ]
    got = [(t.txid, t.symbol, t.quantity) for t in doc.transactions]
    assert got == [("0xb1", "ETH", Decimal("0.05")), ("0xk1", "ETH", Decimal("0.488379"))]
    scans = {
        (urlsplit(u).netloc, query(u).get("chainid"), query(u).get("apikey"))
        for _m, u, _h in fake.calls
        if "etherscan" in u
    }
    assert scans == {
        ("api.routescan.io", None, None),  # Ethereum sans clé
        ("api.etherscan.io", "8453", "cle-gratuite"),
        ("api.etherscan.io", "137", "cle-gratuite"),
    }
    assert env.memory.get("chain_txs") == [
        "crypto:coinbase-wallet",
        "crypto:coinbase-wallet@base",
        "crypto:coinbase-wallet@polygon",
    ]


def test_a_network_without_etherscan_key_is_flagged_and_read_later(make_env: Any) -> None:
    wallet = {
        "account": "crypto:coinbase-wallet",
        "asset": "ETH",
        "addresses": [ETH_ME],
        "networks": ["ethereum", "arbitrum"],
    }
    env = make_env("market", creds={"wallets": [wallet]})
    fake = chain()
    result = market.run(env, "run", Http(fake))
    # le solde Arbitrum est lu (nœud public), son historique attend la clé
    assert result.detail == "partial history.coinbase-wallet.arbitrum:needs_key"
    assert not [u for _m, u, _h in fake.calls if "api.etherscan.io" in u]
    assert env.memory.get("chain_txs") == ["crypto:coinbase-wallet"]
    env.creds["etherscan_key"] = "cle-gratuite"
    market.run(env, "run", Http(fake))
    arbitrum = [query(u) for _m, u, _h in fake.calls if "chainid=42161" in u]
    assert len(arbitrum) == 3  # relu en entier : une page par liste, toutes courtes
    assert "crypto:coinbase-wallet@arbitrum" in env.memory.get("chain_txs")


def test_an_unknown_network_is_refused(make_env: Any) -> None:
    wallet = {"account": "crypto:x", "asset": "ETH", "addresses": [ETH_ME], "networks": ["mars"]}
    env = make_env("market", creds={"wallets": [wallet]})
    with pytest.raises(Failure) as err:
        market.wallet_entries(env)
    assert err.value.outcome == "auth_error"


def test_a_wallet_down_is_left_out_whole_and_retried(make_env: Any) -> None:
    creds = {
        "wallets": [
            {"account": "crypto:ledger", "asset": "BTC", "addresses": [RECEIVE_0]},
            {"account": "crypto:phantom", "asset": "SOL", "addresses": ["Sol1"]},
            {"account": "crypto:vide", "asset": "BTC", "addresses": [CHANGE_0]},
        ]
    }
    env = make_env("market", creds=creds)
    result = market.run(env, "run", Http(chain({RECEIVE_0: 10}, broken="mainnet-beta")))
    assert (result.outcome, result.detail) == ("ok", "partial wallet.phantom:site_unavailable")
    assert held(dropped(env)[0]) == [
        ("crypto:ledger", "CRYPTO:BTC", Decimal("1E-7")),
        ("crypto:vide", "CRYPTO:BTC", Decimal("0")),  # vide : un relevé à zéro, pas d'ancien solde
    ]
    assert env.memory.get("last_run") is None


# --- plateformes ---------------------------------------------------------------------------------


def query(url: str) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}


EMPTY_HISTORY: dict[str, Any] = {
    "/sapi/v1/capital/deposit/hisrec": [],
    "/sapi/v1/capital/withdraw/history": [],
    "/sapi/v1/fiat/orders": {"data": []},
    "/sapi/v1/fiat/payments": {"data": []},
    "/sapi/v1/convert/tradeFlow": {"list": []},
    "/sapi/v1/simple-earn/flexible/history/rewardsRecord": {"rows": [], "total": 0},
    "/sapi/v1/simple-earn/locked/history/rewardsRecord": {"rows": [], "total": 0},
    "/sapi/v1/asset/assetDividend": {"rows": [], "total": 0},
    "/sapi/v1/asset/dribblet": {"total": 0, "userAssetDribblets": []},
    "/api/v3/myTrades": [],
}


def binance_api(
    spot: list[dict[str, str]] | None = None,
    status: int = 200,
    history: Callable[[str, dict[str, str]], Any] | None = None,
) -> Fake:
    def route(method: str, url: str, headers: dict[str, str], data: bytes | None) -> Any:
        path = urlsplit(url).path
        if path == "/api/v3/exchangeInfo":
            return 200, {"symbols": SYMBOLS}
        if path == "/api/v3/klines" or "frankfurter" in url:
            assert history is not None
            found = history(path if "klines" in path else "fx", query(url))
            return (found, b"") if isinstance(found, int) else (200, found)
        assert headers["X-MBX-APIKEY"] == "cle-test"
        raw = urlsplit(url).query
        unsigned, signature = raw.rsplit("&signature=", 1)
        expected = hmac.new(b"secret-test", unsigned.encode(), hashlib.sha256).hexdigest()
        assert signature == expected
        assert {"timestamp", "recvWindow"} <= set(query(url))
        if status != 200:
            return status, {"code": -2015}
        if path in EMPTY_HISTORY:
            found = history(path, query(url)) if history else None
            if isinstance(found, int):
                return found, b""
            return 200, EMPTY_HISTORY[path] if found is None else found
        if path.endswith("/flexible/position"):
            rows = [{"asset": "BTC", "totalAmount": "0.1"}] if query(url)["current"] == "1" else []
            return 200, {"rows": rows, "total": 1}
        if path.endswith("/locked/position"):
            return 200, {"rows": [{"asset": "ETH", "amount": "1.5"}], "total": 1}
        if path == "/api/v3/account":
            return 200, {
                "balances": spot
                or [
                    {"asset": "BTC", "free": "0.2", "locked": "0.05"},
                    {"asset": "LDBTC", "free": "0.1", "locked": "0"},  # double de Simple Earn
                    {"asset": "LDO", "free": "3", "locked": "0"},  # Lido, pas un double
                ]
            }
        if path == "/sapi/v1/asset/get-funding-asset":
            assert method == "POST"
            return 200, [
                {"asset": "USDT", "free": "10", "locked": "0", "freeze": "0", "withdrawing": "0"}
            ]
        raise AssertionError(url)

    return Fake(route)


def test_binance_signs_and_sums_spot_funding_and_earn(make_env: Any) -> None:
    env = make_env("binance")
    fake = binance_api()
    result = binance.run(env, "run", Http(fake))
    assert (result.outcome, result.files) == ("ok", 1)
    (doc,) = dropped(env)
    assert held(doc) == [
        ("crypto:binance", "CRYPTO:BTC", Decimal("0.35")),
        ("crypto:binance", "CRYPTO:ETH", Decimal("1.5")),
        ("crypto:binance", "CRYPTO:LDO", Decimal("3")),
        ("crypto:binance", "CRYPTO:USDT", Decimal("10")),
    ]
    assert binance.run(env, "run", Http(binance_api())).outcome == "nothing_new"


def test_binance_check_drops_nothing_and_a_revoked_key_is_auth_error(make_env: Any) -> None:
    env = make_env("binance")
    assert binance.run(env, "check", Http(binance_api())).outcome == "ok"
    assert dropped(env) == []
    with pytest.raises(Failure) as exc:
        binance.run(env, "run", Http(binance_api(status=401)))
    assert exc.value.outcome == "auth_error"
    with pytest.raises(Failure) as exc:
        binance.run(make_env("binance", creds={"api_key": "k"}), "run", Http(binance_api()))
    assert exc.value.detail == "secret:api_secret"


def test_exchange_account_secret_and_empty_platform(make_env: Any) -> None:
    creds = {"api_key": "cle-test", "api_secret": "secret-test", "account": "crypto:bnb-1"}
    env = make_env("binance", creds=creds)
    binance.run(env, "run", Http(binance_api(spot=[{"asset": "X", "free": "0", "locked": "0"}])))
    assert held(dropped(env)[0])[0][0] == "crypto:bnb-1"
    with pytest.raises(Failure) as exc:
        binance.run(
            make_env("binance", creds={**creds, "account": "Binance"}), "run", Http(binance_api())
        )
    assert exc.value.detail == "secret:account"


SYMBOLS = [
    {"symbol": "BTCUSDT", "baseAsset": "BTC", "quoteAsset": "USDT"},
    {"symbol": "ETHBTC", "baseAsset": "ETH", "quoteAsset": "BTC"},
    {"symbol": "BNBUSDT", "baseAsset": "BNB", "quoteAsset": "USDT"},
    {"symbol": "DOGEUSDT", "baseAsset": "DOGE", "quoteAsset": "USDT"},  # jamais détenu
]
CLOSES = {"BTC": "60000", "ETH": "3000", "BNB": "500", "LDO": "2"}  # XRP : pas de paire USDT


def at(day: str, hour: int = 12) -> int:
    return int(datetime.fromisoformat(f"{day}T{hour:02d}:00:00+00:00").timestamp()) * 1000


BINANCE_ROWS: dict[str, list[dict[str, Any]]] = {
    "/sapi/v1/capital/deposit/hisrec": [
        {
            "id": "d1",
            "amount": "0.01",
            "coin": "BTC",
            "network": "BTC",
            "status": 1,
            "address": "bc1qbinance",
            "txId": "aa11",
            "insertTime": at("2026-03-05"),
        },
        {"id": "d2", "amount": "5", "coin": "BTC", "status": 0, "insertTime": at("2026-03-06")},
    ],
    "/sapi/v1/capital/withdraw/history": [
        {
            "id": "w1",
            "amount": "0.005",
            "transactionFee": "0.0001",
            "coin": "BTC",
            "status": 6,
            "address": "bc1qledger",
            "txId": "bb22",
            "network": "BTC",
            "_ms": at("2026-04-01"),
            "applyTime": "2026-04-01 10:00:00",
            "completeTime": "2026-04-01 10:30:00",
        },
    ],
    "/sapi/v1/fiat/orders": [
        {
            "orderNo": "f1",
            "fiatCurrency": "CHF",
            "indicatedAmount": "1000.00",
            "amount": "999.00",
            "totalFee": "1.00",
            "status": "Successful",
            "createTime": at("2026-03-01"),
            "_type": "0",
        },
    ],
    "/sapi/v1/fiat/payments": [
        {
            "orderNo": "p1",
            "sourceAmount": "102",
            "fiatCurrency": "CHF",
            "obtainAmount": "100",
            "cryptoCurrency": "USDT",
            "totalFee": "2",
            "status": "Completed",
            "createTime": at("2026-03-02"),
            "_type": "0",
        },
    ],
    "/sapi/v1/convert/tradeFlow": [
        {
            "orderId": 77,
            "orderStatus": "SUCCESS",
            "fromAsset": "USDT",
            "fromAmount": "10",
            "toAsset": "ETH",
            "toAmount": "0.005",
            "createTime": at("2026-04-03"),
        },
    ],
    "/sapi/v1/simple-earn/flexible/history/rewardsRecord": [
        {"asset": "USDT", "rewards": "0.2", "type": "REALTIME", "time": at("2026-04-02", 1)},
        {"asset": "USDT", "rewards": "0.3", "type": "REALTIME", "time": at("2026-04-02", 2)},
        {"asset": "USDT", "rewards": "0.1", "type": "REALTIME", "time": at("2026-10-27", 1)},
    ],
    "/sapi/v1/simple-earn/locked/history/rewardsRecord": [
        {"positionId": 1, "asset": "ETH", "amount": "0.001", "time": at("2026-04-10")},
    ],
    "/sapi/v1/asset/assetDividend": [
        {
            "id": 5,
            "tranId": 9,
            "amount": "0.5",
            "asset": "BNB",
            "divTime": at("2026-04-05"),
            "enInfo": "BNB Vault",
        },
        {
            "id": 6,
            "tranId": 10,
            "amount": "1",
            "asset": "USDT",
            "divTime": at("2026-04-06"),
            "enInfo": "Simple Earn Flexible Interest",
        },  # déjà dans les récompenses
    ],
}
DUST = {
    "total": 1,
    "userAssetDribblets": [
        {
            "operateTime": at("2026-04-07"),
            "transId": 45,
            "userAssetDribbletDetails": [
                {
                    "fromAsset": "LDO",
                    "amount": "3",
                    "transferedAmount": "0.00098",
                    "serviceChargeAmount": "0.00002",
                },
                {
                    "fromAsset": "XRP",
                    "amount": "0.5",
                    "transferedAmount": "0.0002",
                    "serviceChargeAmount": "0",
                },
            ],
        }
    ],
}
FILLS = [
    {
        "symbol": "BTCUSDT",
        "id": 100,
        "orderId": 9,
        "qty": "0.0006",
        "quoteQty": "36",
        "commission": "0.00005",
        "commissionAsset": "BNB",
        "time": at("2026-03-03"),
        "isBuyer": True,
    },
    {
        "symbol": "BTCUSDT",
        "id": 101,
        "orderId": 9,
        "qty": "0.0004",
        "quoteQty": "24",
        "commission": "0.00003",
        "commissionAsset": "BNB",
        "time": at("2026-03-03"),
        "isBuyer": True,
    },
]
TIME_KEYS = ("insertTime", "_ms", "createTime", "time", "divTime")


def binance_history_route(
    broken: str | None = None, code: int = 503
) -> Callable[[str, dict[str, str]], Any]:
    def history(path: str, q: dict[str, str]) -> Any:
        if broken and broken in path:
            return code
        if path == "fx":
            return {"rates": {"2026-03-01": {"USD": "1.25"}, "2026-04-01": {"USD": "1.25"}}}
        if path == "/api/v3/klines":
            asset = q["symbol"].removesuffix("USDT")
            if asset not in CLOSES:
                return 400
            day, stop = int(q["startTime"]), int(q["endTime"])
            return [[t, "0", "0", "0", CLOSES[asset]] for t in range(day, stop, 86_400_000)]
        if path == "/sapi/v1/asset/dribblet":
            return DUST
        if "rewardsRecord" in path and int(q["endTime"]) - int(q["startTime"]) > 30 * 86_400_000:
            return 400  # -6021 « Query time range too large »
        if path == "/api/v3/myTrades":
            return [f for f in FILLS if f["symbol"] == q["symbol"] and f["id"] >= int(q["fromId"])]
        rows = BINANCE_ROWS.get(path, [])
        start = int(q.get("startTime") or q.get("beginTime") or 0)
        end = int(q.get("endTime") or 0)
        rows = [
            r
            for r in rows
            if start <= next(r[k] for k in TIME_KEYS if k in r) <= end
            and r.get("_type", q.get("transactionType")) == q.get("transactionType")
            and q.get("page", "1") == "1"
            and q.get("type", "REALTIME") == r.get("type", "REALTIME")
        ]
        if path.startswith("/sapi/v1/fiat"):
            return {"data": rows}
        if path == "/sapi/v1/convert/tradeFlow":
            return {"list": rows}
        if "rewardsRecord" in path or "assetDividend" in path:
            return {"rows": rows, "total": len(rows)}
        return rows

    return history


def ops_of(doc: finance_market.MarketFile) -> list[tuple[str, str, list[tuple[str, str, str]]]]:
    return [
        (o.on_date, o.id, [(leg.symbol, assets_text(leg.quantity), leg.role) for leg in o.legs])
        for o in doc.operations
    ]


def assets_text(q: Decimal) -> str:
    return format(q.normalize(), "f")


def test_binance_history_reads_every_stream_once(make_env: Any, binance_pauses: list[int]) -> None:
    env = make_env("binance")
    fake = binance_api(history=binance_history_route())
    result = binance.run(env, "run", Http(fake))
    assert (result.outcome, result.detail) == ("ok", None)
    (doc,) = dropped(env)
    assert ops_of(doc) == [
        ("2026-03-01", "fiat:f1", [("CHF", "1000", "deposit"), ("CHF", "-1", "fee")]),
        (
            "2026-03-02",
            "payment:p1",
            [
                ("CHF", "102", "deposit"),
                ("CHF", "-100", "trade"),
                ("CHF", "-2", "fee"),
                ("USDT", "100", "trade"),
            ],
        ),
        (
            "2026-03-03",
            "trade:BTCUSDT:9:100",  # deux exécutions du même ordre
            [("BTC", "0.001", "trade"), ("USDT", "-60", "trade"), ("BNB", "-0.00008", "fee")],
        ),
        ("2026-03-05", "deposit:d1", [("BTC", "0.01", "deposit")]),
        (
            "2026-04-01",
            "withdraw:w1",
            [("BTC", "-0.005", "withdrawal"), ("BTC", "-0.0001", "fee")],
        ),
        ("2026-04-02", "reward:flexible:USDT:2026-04-02", [("USDT", "0.5", "income")]),
        (
            "2026-04-03",
            "convert:77",
            [("USDT", "-10", "trade"), ("ETH", "0.005", "trade")],
        ),
        ("2026-04-05", "dividend:9", [("BNB", "0.5", "income")]),
        (
            "2026-04-07",
            "dust:45",
            [
                ("LDO", "-3", "trade"),
                ("BNB", "0.001", "trade"),
                ("BNB", "-0.00002", "fee"),
                ("XRP", "-0.5", "trade"),
                ("BNB", "0.0002", "trade"),
            ],
        ),
        ("2026-04-10", "reward:locked:ETH:2026-04-10", [("ETH", "0.001", "income")]),
    ]
    deposit = next(o for o in doc.operations if o.id == "deposit:d1")
    assert (deposit.txid, deposit.address, deposit.network) == ("aa11", "bc1qbinance", "BTC")
    # les cours Binance des seuls jours d'opération ; XRP sans paire USDT est laissé
    binance_prices = sorted((p.key, p.on_date) for p in doc.prices)
    assert binance_prices == [
        ("CRYPTO:BNB", "2026-03-03"),
        ("CRYPTO:BNB", "2026-04-05"),
        ("CRYPTO:BNB", "2026-04-07"),
        ("CRYPTO:BTC", "2026-03-03"),
        ("CRYPTO:BTC", "2026-03-05"),
        ("CRYPTO:BTC", "2026-04-01"),
        ("CRYPTO:ETH", "2026-04-03"),
        ("CRYPTO:ETH", "2026-04-10"),
        ("CRYPTO:LDO", "2026-04-07"),
    ]
    assert {(f.on_date, f.base) for f in doc.fx} == {("2026-03-01", "USD"), ("2026-04-01", "USD")}
    # les retraits ne sont lus qu'à partir du premier apport, à dix appels par minute
    withdrawals = [query(u) for _m, u, _h in fake.calls if "withdraw/history" in u]
    assert int(withdrawals[0]["startTime"]) == at("2026-03-01", 0)
    assert binance_pauses.count(6_000) == len(withdrawals) == 3
    # les paires des actifs connus seulement
    pairs = {query(u)["symbol"] for _m, u, _h in fake.calls if "myTrades" in u}
    assert pairs == {"BTCUSDT", "ETHBTC", "BNBUSDT"}
    assert env.memory.get("history_since") == "2026-10-27"
    assert env.memory.get("trade_ids") == {"BTCUSDT": 102}
    assert env.memory.get("first_day") == "2026-03-01"
    assert env.memory.get("rewards_since") == "2026-10-27"
    later = binance_api(history=binance_history_route())
    assert binance.run(env, "run", Http(later)).outcome == "ok"
    # ensuite : quelques jours de recouvrement, les exécutions suivantes, ni cours ni change
    deposits = [query(u) for _m, u, _h in later.calls if "deposit/hisrec" in u]
    assert [int(q["startTime"]) for q in deposits] == [at("2026-10-24", 0)]
    trades = [query(u) for _m, u, _h in later.calls if "myTrades" in u]
    assert {q["symbol"]: q["fromId"] for q in trades}["BTCUSDT"] == "102"
    assert not [u for _m, u, _h in later.calls if "klines" in u or "frankfurter" in u]
    assert [bool(d.operations) for d in dropped(env)].count(False) == 1


def test_binance_rewards_missed_before_are_read_again(make_env: Any) -> None:
    """Un historique lu sans ses récompenses (fenêtres refusées jusqu'à la v0.9.9) : le passage
    suivant les relit depuis la première opération, le reste en recouvrement seulement."""
    env = make_env("binance")
    env.memory.put("history_since", "2026-10-26")
    env.memory.put("first_day", "2026-03-01")
    fake = binance_api(history=binance_history_route())
    assert binance.run(env, "run", Http(fake)).detail is None
    ops = [o.id for d in dropped(env) for o in d.operations if o.kind == "reward"]
    assert ops == ["reward:flexible:USDT:2026-04-02", "reward:locked:ETH:2026-04-10"]
    earn = [query(u) for _m, u, _h in fake.calls if "locked/history" in u]
    assert int(earn[0]["startTime"]) == at("2026-03-01", 0)
    assert env.memory.get("rewards_since") == "2026-10-27"
    again = binance_api(history=binance_history_route())
    binance.run(env, "run", Http(again))
    earn = [query(u) for _m, u, _h in again.calls if "locked/history" in u]
    assert [int(q["startTime"]) for q in earn] == [at("2026-10-24", 0)]


def test_binance_first_history_is_all_or_nothing(make_env: Any) -> None:
    env = make_env("binance")
    fake = binance_api(history=binance_history_route(broken="convert"))
    result = binance.run(env, "run", Http(fake))
    assert result.detail == "partial convert:site_unavailable"
    (doc,) = dropped(env)
    assert (doc.operations, doc.prices) == ([], [])  # les soldes, pas l'historique
    assert len(doc.balances) == 4
    assert env.memory.get("history_since") is None
    assert env.memory.get("trade_ids") is None
    # une fenêtre refusée (400 : trop ancienne pour ce flux) est comptée, pas fatale
    env = make_env("binance", creds={"api_key": "cle-test", "api_secret": "secret-test"})
    route = binance_history_route("dribblet", code=400)
    refused = binance.run(env, "run", Http(binance_api(history=route)))
    assert refused.detail == "partial dust:skipped=1"
    assert max(len(d.operations) for d in dropped(env)) == 9
    assert env.memory.get("history_since") == "2026-10-27"


def kucoin_api(
    code: str = "200000", ledger: Callable[[dict[str, str]], list[Any]] = lambda _q: []
) -> Fake:
    def route(method: str, url: str, headers: dict[str, str], data: bytes | None) -> Any:
        if "kucoin" not in url:
            return 200, [] if "binance" in url else {"rates": {}}
        path = url.split("api.kucoin.com", 1)[1]
        stamp = headers["KC-API-TIMESTAMP"]

        def sign(message: str) -> str:
            mac = hmac.new(b"secret-test", message.encode(), hashlib.sha256).digest()
            return base64.b64encode(mac).decode()

        assert headers["KC-API-SIGN"] == sign(stamp + "GET" + path)
        assert headers["KC-API-PASSPHRASE"] == sign("phrase")
        assert (headers["KC-API-KEY"], headers["KC-API-KEY-VERSION"]) == ("cle-test", "2")
        if code != "200000":
            return 200, {"code": code, "msg": "refusé"}
        if path == "/api/v1/accounts":
            return 200, {
                "code": "200000",
                "data": [
                    {"currency": "BTC", "type": "main", "balance": "0.01"},
                    {"currency": "BTC", "type": "trade", "balance": "0.02"},
                    {"currency": "KCS", "type": "main", "balance": "0"},
                ],
            }
        if path.startswith("/api/v1/accounts/ledgers"):
            return 200, {"code": "200000", "data": {"items": ledger(query(url)), "totalPage": 1}}
        page = query(url)["currentPage"]
        items = [{"currency": "USDT", "holdAmount": "100" if page == "1" else "5"}]
        return 200, {"code": "200000", "data": {"items": items, "totalPage": 2}}

    return Fake(route)


def test_kucoin_signs_and_sums_accounts_and_earn(make_env: Any) -> None:
    env = make_env("kucoin")
    assert kucoin.run(env, "run", Http(kucoin_api())).outcome == "ok"
    assert held(dropped(env)[0]) == [
        ("crypto:kucoin", "CRYPTO:BTC", Decimal("0.03")),
        ("crypto:kucoin", "CRYPTO:USDT", Decimal("105")),
    ]
    with pytest.raises(Failure) as exc:
        kucoin.run(env, "run", Http(kucoin_api("400003")))
    assert (exc.value.outcome, exc.value.detail) == ("auth_error", "kucoin.accounts:400003")
    with pytest.raises(Failure) as exc:
        kucoin.run(env, "run", Http(kucoin_api("500000")))
    assert exc.value.outcome == "site_unavailable"


def b64url_decode(part: str) -> bytes:
    return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))


def coinbase_api(
    verify: Callable[[bytes, bytes, dict[str, Any]], None],
    transactions: Callable[[str, dict[str, str]], list[Any]] = lambda _p, _q: [],
) -> Fake:
    def route(method: str, url: str, headers: dict[str, str], data: bytes | None) -> Any:
        if "coinbase" not in url:
            return 200, [] if "binance" in url else {"rates": {"2026-05-01": {"USD": "1.25"}}}
        token = headers["Authorization"].removeprefix("Bearer ")
        head, body, sig = token.split(".")
        claims = json.loads(b64url_decode(body))
        path = urlsplit(url).path
        assert claims["uri"] == f"GET api.coinbase.com{path}"
        assert (claims["sub"], claims["iss"], claims["exp"] - claims["nbf"]) == (
            "organizations/o/apiKeys/k",
            "cdp",
            120,
        )
        header = json.loads(b64url_decode(head))
        assert header["kid"] == "organizations/o/apiKeys/k"
        verify(f"{head}.{body}".encode(), b64url_decode(sig), header)
        if path.endswith("/transactions"):
            return 200, {"data": transactions(path, query(url)), "pagination": {}}
        if "starting_after" not in url:
            accounts = [
                {"id": "eth", "balance": {"amount": "0.5", "currency": "ETH"}},
                {"id": "eth2", "balance": {"amount": "1.25", "currency": "ETH2"}},  # en staking
            ]
            next_uri = "/v2/accounts?limit=100&starting_after=abc"
            return 200, {"data": accounts, "pagination": {"next_uri": next_uri}}
        accounts = [{"id": "usdc", "balance": {"amount": "20", "currency": "USDC"}}]
        return 200, {"data": accounts, "pagination": {"next_uri": None}}

    return Fake(route)


def test_coinbase_signs_es256_jwt_and_follows_pages(make_env: Any) -> None:
    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    ).decode()

    def verify(signed: bytes, sig: bytes, header: dict[str, Any]) -> None:
        assert header["alg"] == "ES256"
        assert len(sig) == 64
        der = encode_dss_signature(int.from_bytes(sig[:32]), int.from_bytes(sig[32:]))
        key.public_key().verify(der, signed, ec.ECDSA(hashes.SHA256()))

    creds = {"key_name": "organizations/o/apiKeys/k", "private_key": pem.replace("\n", "\\n")}
    env = make_env("coinbase", creds=creds)
    fake = coinbase_api(verify)
    assert coinbase.run(env, "run", Http(fake)).outcome == "ok"
    # les soldes (deux pages), puis l'historique : les portefeuilles et leurs transactions
    paths = [urlsplit(u).path for _m, u, _h in fake.calls]
    assert paths.count("/v2/accounts") == 4
    assert sorted(p for p in paths if p.endswith("/transactions")) == [
        "/v2/accounts/eth/transactions",
        "/v2/accounts/eth2/transactions",
        "/v2/accounts/usdc/transactions",
    ]
    assert held(dropped(env)[0]) == [
        ("crypto:coinbase", "CRYPTO:ETH", Decimal("1.75")),
        ("crypto:coinbase", "CRYPTO:USDC", Decimal("20")),
    ]


def test_coinbase_ed25519_key_and_bad_key(make_env: Any) -> None:
    key = ed25519.Ed25519PrivateKey.generate()
    raw = key.private_bytes(
        serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption()
    )
    public = key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )

    def verify(signed: bytes, sig: bytes, header: dict[str, Any]) -> None:
        assert header["alg"] == "EdDSA"
        key.public_key().verify(sig, signed)

    secret = base64.b64encode(raw + public).decode()
    creds = {"key_name": "organizations/o/apiKeys/k", "private_key": secret}
    assert (
        coinbase.run(make_env("coinbase", creds=creds), "check", Http(coinbase_api(verify))).outcome
        == "ok"
    )
    bad = {
        **creds,
        "private_key": "-----BEGIN EC PRIVATE KEY-----\nabc\n-----END EC PRIVATE KEY-----",
    }
    with pytest.raises(Failure) as exc:
        coinbase.run(make_env("coinbase", creds=bad), "run", Http(coinbase_api(verify)))
    assert (exc.value.outcome, exc.value.detail) == ("auth_error", "secret:private_key")


COINBASE_TXS: dict[str, list[dict[str, Any]]] = {
    "eth": [  # de la plus récente à la plus ancienne
        {
            "id": "t5",
            "type": "weird_type",
            "status": "completed",
            "amount": {"amount": "1", "currency": "ETH"},
            "created_at": "2026-08-01T10:00:00Z",
        },
        {
            "id": "t4",
            "type": "staking_transfer",
            "status": "completed",
            "amount": {"amount": "-0.2", "currency": "ETH"},
            "created_at": "2026-07-15T10:00:00Z",
        },
        {
            "id": "t2",
            "type": "send",
            "status": "completed",
            "amount": {"amount": "-0.101", "currency": "ETH"},
            "native_amount": {"amount": "-303.00", "currency": "CHF"},
            "created_at": "2026-06-01T10:00:00Z",
            "network": {
                "hash": "0xabc",
                "transaction_fee": {"amount": "0.001", "currency": "ETH"},
                "transaction_amount": {"amount": "0.1", "currency": "ETH"},
            },
        },
        {
            "id": "t6",
            "type": "send",
            "status": "pending",
            "amount": {"amount": "-1", "currency": "ETH"},
            "created_at": "2026-05-20T10:00:00Z",
        },
        {
            "id": "t1",
            "type": "buy",
            "status": "completed",
            "amount": {"amount": "0.5", "currency": "ETH"},
            "native_amount": {"amount": "1500.00", "currency": "CHF"},
            "created_at": "2026-05-01T10:00:00Z",
        },
    ],
    "eth2": [
        {
            "id": "t3",
            "type": "staking_reward",
            "status": "completed",
            "amount": {"amount": "0.01", "currency": "ETH2"},
            "native_amount": {"amount": "30.00", "currency": "CHF"},
            "created_at": "2026-07-01T10:00:00Z",
        },
    ],
}


def coinbase_txs(path: str, _q: dict[str, str]) -> list[Any]:
    return COINBASE_TXS.get(path.split("/")[3], [])


def ed25519_creds() -> dict[str, str]:
    key = ed25519.Ed25519PrivateKey.generate()
    raw = key.private_bytes(
        serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption()
    )
    return {"key_name": "organizations/o/apiKeys/k", "private_key": base64.b64encode(raw).decode()}


def test_coinbase_history_reads_every_wallet(make_env: Any) -> None:
    env = make_env("coinbase", creds=ed25519_creds())
    fake = coinbase_api(lambda *_a: None, coinbase_txs)
    result = coinbase.run(env, "run", Http(fake))
    # un type inconnu est compté, pas importé
    assert (result.outcome, result.detail) == ("ok", "partial type.weird_type:skipped=1")
    (doc,) = dropped(env)
    got = [
        (o.on_date, o.id, o.kind, [(g.symbol, str(g.quantity), g.role, g.value) for g in o.legs])
        for o in doc.operations
    ]
    assert got == [
        ("2026-05-01", "tx:t1", "trade", [("ETH", "0.5", "trade", Decimal("1500.00"))]),
        # un envoi : le montant parti et les frais de réseau, à leur cours
        (
            "2026-06-01",
            "tx:t2",
            "withdrawal",
            [("ETH", "-0.1", "withdrawal", None), ("ETH", "-0.001", "fee", None)],
        ),
        ("2026-07-01", "tx:t3", "reward", [("ETH", "0.01", "income", Decimal("30.00"))]),
    ]
    assert doc.operations[1].txid == "0xabc"
    assert env.memory.get("history_since") == "2026-10-27"
    # ensuite : rien de plus vieux que trois jours avant le dernier passage
    later = coinbase_api(lambda *_a: None, coinbase_txs)
    coinbase.run(env, "run", Http(later))
    assert [len(d.operations) for d in dropped(env)].count(0) == 1


def ledger_rows(q: dict[str, str]) -> list[Any]:
    start, end = int(q["startAt"]), int(q["endAt"])
    rows = [
        {
            "id": "l1",
            "currency": "BTC",
            "amount": "0.1",
            "fee": "0",
            "direction": "in",
            "bizType": "Deposit",
            "createdAt": at("2026-09-01"),
            "context": '{"txId":"kk1"}',
        },
        {
            "id": "l2",
            "currency": "BTC",
            "amount": "0.05",
            "fee": "0",
            "direction": "out",
            "bizType": "Exchange",
            "createdAt": at("2026-09-02"),
            "context": '{"orderId":"o1"}',
        },
        {
            "id": "l3",
            "currency": "USDT",
            "amount": "3000",
            "fee": "3",
            "direction": "in",
            "bizType": "Exchange",
            "createdAt": at("2026-09-02"),
            "context": '{"orderId":"o1"}',
        },
        {
            "id": "l4",
            "currency": "USDT",
            "amount": "100",
            "fee": "0",
            "direction": "out",
            "bizType": "Transfer",
            "createdAt": at("2026-09-03"),
            "context": "",
        },
        {
            "id": "l5",
            "currency": "KCS",
            "amount": "1",
            "fee": "0",
            "direction": "in",
            "bizType": "Mystery",
            "createdAt": at("2026-09-04"),
            "context": "",
        },
        {
            "id": "l6",
            "currency": "USDT",
            "amount": "0.5",
            "fee": "0",
            "direction": "in",
            "bizType": "Staking Rewards",
            "createdAt": at("2026-09-05"),
            "context": "",
        },
    ]
    return [r for r in rows if start <= r["createdAt"] <= end]


def test_kucoin_history_reads_the_ledger_day_by_day(make_env: Any) -> None:
    env = make_env("kucoin")
    fake = kucoin_api(ledger=ledger_rows)
    result = kucoin.run(env, "run", Http(fake))
    assert result.detail == "partial type.Mystery:skipped=1"
    (doc,) = dropped(env)
    got = [
        (o.id, o.kind, [(g.symbol, str(g.quantity), g.role) for g in o.legs])
        for o in doc.operations
    ]
    assert got == [
        ("ledger:l1", "deposit", [("BTC", "0.1", "deposit")]),
        (
            "order:o1:l2",  # les deux côtés de l'ordre
            "trade",
            [("BTC", "-0.05", "trade"), ("USDT", "3000", "trade"), ("USDT", "-3", "fee")],
        ),
        ("ledger:l6", "reward", [("USDT", "0.5", "income")]),
    ]
    assert doc.operations[0].txid == "kk1"
    days = [query(u) for _m, u, _h in fake.calls if "ledgers" in u]
    assert len(days) == 365  # un an, par tranches de 24 heures
    later = kucoin_api(ledger=ledger_rows)
    kucoin.run(env, "run", Http(later))
    assert (
        len([u for _m, u, _h in later.calls if "ledgers" in u]) == 4
    )  # trois jours de recouvrement


def test_mempool_rate_limit_is_paced_and_retried(make_env: Any, pauses: list[int]) -> None:
    creds = {"wallets": [{"account": "crypto:ledger", "asset": "BTC", "addresses": [RECEIVE_0]}]}
    refusals = [429, 429]
    inner = chain({RECEIVE_0: 100_000_000})

    def route(method: str, url: str, headers: dict[str, str], data: bytes | None) -> Any:
        if "mempool" in url and refusals:
            return refusals.pop(), b""
        status, body = inner.route(method, url, headers, data)
        return status, body

    env = make_env("market", creds=creds, market={"coingecko_pause_seconds": 0})
    assert market.run(env, "run", Http(Fake(route))).detail is None
    # une seconde avant chaque requête, 10 s puis 30 s ; la dernière lit l'historique
    assert pauses == [1, 10, 1, 30, 1, 1]
    assert held(dropped(env)[0]) == [("crypto:ledger", "CRYPTO:BTC", Decimal("1"))]
    pauses.clear()
    refusals.extend([429] * 4)
    again = market.run(
        make_env("market", creds=creds, market={"coingecko_pause_seconds": 0}),
        "run",
        Http(Fake(route)),
    )
    assert again.detail == "partial wallet.ledger:site_unavailable"
    assert [p for p in pauses if p > 1] == [10, 30, 60]


# --- historique BTC ------------------------------------------------------------------------------

A, B, OUT = "bc1qmienne-a", "bc1qmienne-b", "bc1qailleurs"
DAY1, DAY2 = 1_709_294_400, 1_717_243_200  # 2024-03-01 et 2024-06-01 à 12:00 UTC
HISTORY = {
    A: [  # des plus récentes aux plus anciennes, comme mempool.space
        {
            "txid": "t2",
            "status": {"confirmed": True, "block_time": DAY2},
            "fee": 10_000_000,
            "vin": [{"prevout": {"scriptpubkey_address": A, "value": 100_000_000}}],
            "vout": [
                {"scriptpubkey_address": OUT, "value": 40_000_000},
                {"scriptpubkey_address": B, "value": 50_000_000},  # monnaie, frais 0.1
            ],
        },
        {
            "txid": "t1",
            "status": {"confirmed": True, "block_time": DAY1},
            "vin": [{"prevout": {"scriptpubkey_address": OUT, "value": 100_010_000}}],
            "vout": [{"scriptpubkey_address": A, "value": 100_000_000}],
        },
    ],
    B: [
        {
            "txid": "t2",
            "status": {"confirmed": True, "block_time": DAY2},
            "fee": 10_000_000,
            "vin": [{"prevout": {"scriptpubkey_address": A, "value": 100_000_000}}],
            "vout": [
                {"scriptpubkey_address": OUT, "value": 40_000_000},
                {"scriptpubkey_address": B, "value": 50_000_000},
            ],
        },
        {"txid": "t3", "status": {"confirmed": False}, "vin": [], "vout": []},
    ],
}


def history_api(broken: str | None = None) -> Fake:
    base = chain({A: 0, B: 50_000_000})

    def route(method: str, url: str, headers: dict[str, str], data: bytes | None) -> Any:
        if broken and broken in url:
            return 503, b""
        if "/txs/chain" in url:
            address = url.split("/address/", 1)[1].split("/", 1)[0]
            return 200, HISTORY[address]
        if "api.binance.com" in url:
            q = query(url)
            assert (q["symbol"], q["interval"]) == ("BTCUSDT", "1d")
            day = 86_400_000
            first = int(q["startTime"])
            if first != 1_709_251_200_000:  # 2024-03-01 00:00 UTC : une seule page
                return 200, []
            return 200, [
                [first, "1", "2", "0.5", "60000.5", "9"],
                [first + day, "1", "2", "0", "61000"],
            ]
        return base.route(method, url, headers, data)

    return Fake(route)


def test_btc_history_is_read_once_from_the_chain(make_env: Any) -> None:
    creds = {"wallets": [{"account": "crypto:ledger", "asset": "BTC", "addresses": [A, B]}]}
    env = make_env("market", creds=creds)
    fake = history_api()
    result = market.run(env, "run", Http(fake))
    assert (result.outcome, result.detail) == ("ok", None)
    (doc,) = dropped(env)
    assert [(b.on_date, b.quantity) for b in doc.balances] == [
        ("2026-10-27", Decimal("0.5")),  # aujourd'hui
        ("2024-03-01", Decimal("1")),  # reçu
        ("2024-06-01", Decimal("0.5")),  # 0.4 envoyé, 0.1 de frais, la monnaie reste à soi
    ]
    # l'historique remonte avant la fenêtre d'un an : change BCE et clôtures Binance en USD
    fx_urls = [u for _m, u, _h in fake.calls if "frankfurter" in u]
    assert "/2024-03-01..2025-10-27?" in fx_urls[1]
    binance = [p for p in doc.prices if p.source == "binance"]
    assert [(p.on_date, p.price, p.currency) for p in binance] == [
        ("2024-03-01", Decimal("60000.5"), "USD"),
        ("2024-03-02", Decimal("61000"), "USD"),
    ]
    assert env.memory.get("btc_history") == ["crypto:ledger"]
    # chaque transaction part aussi au registre : net (frais compris) et frais payés
    assert [(t.on_date, t.txid, t.quantity, t.fee) for t in doc.transactions] == [
        ("2024-03-01", "t1", Decimal(1), Decimal(0)),
        ("2024-06-01", "t2", Decimal("-0.5"), Decimal("0.1")),
    ]
    assert env.memory.get("btc_txs") == ["crypto:ledger"]
    later = history_api()
    market.run(env, "run", Http(later))
    # ensuite : la dernière page de chaque adresse, sans historique ni cours anciens
    assert not [u for _m, u, _h in later.calls if "/txs/chain/" in u or "api.binance.com" in u]
    assert len(dropped(env)[-1].transactions) == 2


def test_btc_history_pages_and_failures(make_env: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(market, "TXS_PER_PAGE", 2)
    creds = {"wallets": [{"account": "crypto:ledger", "asset": "BTC", "addresses": [A]}]}
    env = make_env("market", creds=creds)
    fake = history_api(broken="api.binance.com")
    result = market.run(env, "run", Http(fake))
    assert result.detail == "partial history_prices:site_unavailable"
    assert any(u.endswith("/txs/chain/t1") for _m, u, _h in fake.calls)  # page suivante
    assert env.memory.get("btc_history") is None  # relu au prochain passage
    down = market.run(make_env("market", creds=creds), "run", Http(history_api(broken="/txs/")))
    assert down.detail == "partial history.ledger:site_unavailable"


def test_coingecko_without_key_is_paced_and_retried(make_env: Any, pauses: list[int]) -> None:
    refusals = [429]
    inner = chain()

    def route(method: str, url: str, headers: dict[str, str], data: bytes | None) -> Any:
        if "coingecko" in url and "solana" in url and refusals:
            return refusals.pop(), b""
        return inner.route(method, url, headers, data)

    crypto = {"BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana"}
    env = make_env("market", market={"crypto": crypto})
    assert market.run(env, "run", Http(Fake(route))).detail is None
    # trois secondes entre deux cours ; le refus attend 10 s et réessaie
    assert pauses == [3, 3, 10, 3]
    pauses.clear()
    keyed = make_env("market", creds={"coingecko_key": "demo"}, market={"crypto": crypto})
    market.run(keyed, "run", Http(Fake(inner.route)))
    assert pauses == []  # avec une clé, pas d'attente


def test_an_etherscan_rate_limit_is_retried(make_env: Any, pauses: list[int]) -> None:
    said = [{"status": "0", "message": "NOTOK", "result": "Max rate limit reached"}]
    inner = chain()

    def route(method: str, url: str, headers: dict[str, str], data: bytes | None) -> Any:
        if "etherscan" in url and said:
            return 200, said.pop()
        return inner.route(method, url, headers, data)

    wallet = {"account": "crypto:metamask", "asset": "ETH", "addresses": [ETH_ME]}
    env = make_env("market", creds={"wallets": [wallet]}, market={"coingecko_pause_seconds": 0})
    assert market.run(env, "run", Http(Fake(route))).detail is None
    assert 10 in pauses


def test_a_network_outside_the_free_plan_is_flagged(make_env: Any) -> None:
    inner = chain()

    def route(method: str, url: str, headers: dict[str, str], data: bytes | None) -> Any:
        if "chainid=56" in url:
            refused = "Free API access is not supported for this chain"
            return 200, {"status": "0", "message": "NOTOK", "result": refused}
        return inner.route(method, url, headers, data)

    wallet = {
        "account": "crypto:trust-wallet",
        "asset": "ETH",
        "addresses": [ETH_ME],
        "networks": ["ethereum", "bsc"],
    }
    creds = {"wallets": [wallet], "etherscan_key": "cle-gratuite"}
    env = make_env("market", creds=creds, market={"coingecko_pause_seconds": 0})
    result = market.run(env, "run", Http(Fake(route)))
    # le solde BNB Smart Chain est lu, son historique signalé ; Ethereum continue
    assert result.detail == "partial history.trust-wallet.bsc:unsupported"
    assert ("crypto:trust-wallet", "CRYPTO:BNB", Decimal("0.5")) in held(dropped(env)[0])
    assert env.memory.get("chain_txs") == ["crypto:trust-wallet"]
