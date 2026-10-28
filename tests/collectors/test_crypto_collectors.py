"""Portefeuilles crypto (xpub, Ethereum et ses jetons, Solana) et plateformes (Binance, KuCoin,
Coinbase) avec un faux transport : adresses dérivées, signatures, soldes lus par Finance."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from collections.abc import Callable
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
    btc: dict[str, int] | None = None, broken: str | None = None, *, sol_owner: str = "Sol1"
) -> Fake:
    """mempool (satoshis par adresse utilisée), nœud Ethereum, RPC Solana, prix et change."""
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


def binance_api(spot: list[dict[str, str]] | None = None, status: int = 200) -> Fake:
    def route(method: str, url: str, headers: dict[str, str], data: bytes | None) -> Any:
        assert headers["X-MBX-APIKEY"] == "cle-test"
        raw = urlsplit(url).query
        unsigned, signature = raw.rsplit("&signature=", 1)
        expected = hmac.new(b"secret-test", unsigned.encode(), hashlib.sha256).hexdigest()
        assert signature == expected
        assert {"timestamp", "recvWindow"} <= set(query(url))
        if status != 200:
            return status, {"code": -2015}
        path = urlsplit(url).path
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


def kucoin_api(code: str = "200000") -> Fake:
    def route(method: str, url: str, headers: dict[str, str], data: bytes | None) -> Any:
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


def coinbase_api(verify: Callable[[bytes, bytes, dict[str, Any]], None]) -> Fake:
    def route(method: str, url: str, headers: dict[str, str], data: bytes | None) -> Any:
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
        if "starting_after" not in url:
            accounts = [
                {"balance": {"amount": "0.5", "currency": "ETH"}},
                {"balance": {"amount": "1.25", "currency": "ETH2"}},  # ETH en staking
            ]
            next_uri = "/v2/accounts?limit=100&starting_after=abc"
            return 200, {"data": accounts, "pagination": {"next_uri": next_uri}}
        accounts = [{"balance": {"amount": "20", "currency": "USDC"}}]
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
    assert len(fake.calls) == 2
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


def test_mempool_rate_limit_is_paced_and_retried(make_env: Any, pauses: list[int]) -> None:
    creds = {"wallets": [{"account": "crypto:ledger", "asset": "BTC", "addresses": [RECEIVE_0]}]}
    refusals = [429, 429]
    inner = chain({RECEIVE_0: 100_000_000})

    def route(method: str, url: str, headers: dict[str, str], data: bytes | None) -> Any:
        if "mempool" in url and refusals:
            return refusals.pop(), b""
        status, body = inner.route(method, url, headers, data)
        return status, body

    env = make_env("market", creds=creds)
    assert market.run(env, "run", Http(Fake(route))).detail is None
    # une seconde avant chaque requête, 10 s puis 30 s ; la dernière lit l'historique
    assert pauses == [1, 10, 1, 30, 1, 1]
    assert held(dropped(env)[0]) == [("crypto:ledger", "CRYPTO:BTC", Decimal("1"))]
    pauses.clear()
    refusals.extend([429] * 4)
    again = market.run(make_env("market", creds=creds), "run", Http(Fake(route)))
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
        if "binance" in url:
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
    assert not [u for _m, u, _h in later.calls if "/txs/chain/" in u or "binance" in u]
    assert len(dropped(env)[-1].transactions) == 2


def test_btc_history_pages_and_failures(make_env: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(market, "TXS_PER_PAGE", 2)
    creds = {"wallets": [{"account": "crypto:ledger", "asset": "BTC", "addresses": [A]}]}
    env = make_env("market", creds=creds)
    fake = history_api(broken="binance")
    result = market.run(env, "run", Http(fake))
    assert result.detail == "partial history_prices:site_unavailable"
    assert any(u.endswith("/txs/chain/t1") for _m, u, _h in fake.calls)  # page suivante
    assert env.memory.get("btc_history") is None  # relu au prochain passage
    down = market.run(make_env("market", creds=creds), "run", Http(history_api(broken="/txs/")))
    assert down.detail == "partial history.ledger:site_unavailable"
