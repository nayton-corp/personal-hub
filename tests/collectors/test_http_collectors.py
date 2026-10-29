"""Collecteurs IBKR (Flex Web Service) et « market » (cours publics) avec un faux transport :
contrôle, dépôt, attente du relevé, échecs typés, fichier lisible par le domaine Finance."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

from hub.collectors.base import Failure
from hub.collectors.http import Http
from hub.collectors.ibkr import flow as ibkr
from hub.collectors.market import flow as market
from hub.collectors.runtime import Env
from hub.domains.finance.sources.infra import market_file
from tests.factories import ibkr as f

Route = Callable[[str, str, bytes | None], tuple[int, bytes]]


class Fake:
    def __init__(self, route: Route) -> None:
        self.route = route
        self.calls: list[tuple[str, str]] = []

    def __call__(
        self, method: str, url: str, headers: dict[str, str], data: bytes | None
    ) -> tuple[int, bytes]:
        self.calls.append((method, url))
        return self.route(method, url, data)


def inbox_files(env: Env) -> list[bytes]:
    return [p.read_bytes() for p in sorted(env.inbox_root.glob("*")) if p.is_file()]


# --- IBKR ---------------------------------------------------------------------------------------

SEND_OK = (
    b"<FlexStatementResponse><Status>Success</Status><ReferenceCode>42</ReferenceCode>"
    b"<Url>https://flex.invalid/GetStatement</Url></FlexStatementResponse>"
)
WAIT = (
    b"<FlexStatementResponse><Status>Warn</Status><ErrorCode>1019</ErrorCode>"
    b"<ErrorMessage>Statement generation in progress</ErrorMessage></FlexStatementResponse>"
)
STATEMENT = f.flex(f.Flex(date(2026, 10, 26), date(2026, 10, 26), cash=[("CHF", "10", "10")]))


def flex_service(gets: list[bytes], send: bytes = SEND_OK) -> Fake:
    def route(method: str, url: str, data: bytes | None) -> tuple[int, bytes]:
        if "/SendRequest" in url:
            q = parse_qs(urlsplit(url).query)
            assert q == {"t": ["jeton-test"], "q": ["123456"], "v": ["3"]}
            return 200, send
        return 200, gets.pop(0)

    return Fake(route)


def test_ibkr_check_sends_request_only(make_env: Any) -> None:
    env = make_env("ibkr")
    fake = flex_service([])
    assert ibkr.run(env, "check", Http(fake)).outcome == "ok"
    assert len(fake.calls) == 1
    assert inbox_files(env) == []


def test_ibkr_run_waits_for_statement_then_drops_it(make_env: Any) -> None:
    env = make_env("ibkr")
    fake = flex_service([WAIT, STATEMENT])
    waits: list[int] = []
    result = ibkr.run(env, "run", Http(fake), sleep=waits.append)
    assert (result.outcome, result.files) == ("ok", 1)
    assert waits == [5, 5]
    assert fake.calls[-1][1].startswith("https://flex.invalid/GetStatement?")
    assert inbox_files(env) == [STATEMENT]
    again = ibkr.run(env, "run", Http(flex_service([STATEMENT])), sleep=waits.append)
    assert again.outcome == "nothing_new"


@pytest.mark.parametrize(
    ("code", "outcome"), [("1015", "auth_error"), ("1018", "site_unavailable"), ("9", "unknown")]
)
def test_ibkr_errors_are_typed(make_env: Any, code: str, outcome: str) -> None:
    send = (
        f"<FlexStatementResponse><Status>Fail</Status><ErrorCode>{code}</ErrorCode>"
        "</FlexStatementResponse>"
    ).encode()
    with pytest.raises(Failure) as exc:
        ibkr.run(make_env("ibkr"), "run", Http(flex_service([], send)), sleep=lambda _s: None)
    assert exc.value.outcome == outcome


def test_ibkr_timeout_and_missing_secret(make_env: Any) -> None:
    with pytest.raises(Failure) as exc:
        ibkr.run(make_env("ibkr"), "run", Http(flex_service([WAIT] * 12)), sleep=lambda _s: None)
    assert exc.value.detail == "flex.get:timeout"
    with pytest.raises(Failure) as exc:
        ibkr.run(make_env("ibkr", creds={}), "check", Http(flex_service([])))
    assert exc.value.outcome == "auth_error"


def test_http_status_mapping() -> None:
    for status, outcome in ((401, "auth_error"), (500, "site_unavailable")):
        with pytest.raises(Failure) as exc:
            Http(Fake(lambda m, u, d, s=status: (s, b""))).call("https://x.invalid", "step")
        assert exc.value.outcome == outcome

    def down(m: str, u: str, d: bytes | None) -> tuple[int, bytes]:
        raise OSError

    with pytest.raises(Failure) as exc:
        Http(Fake(down)).call("https://x.invalid", "step")
    assert exc.value.detail == "step:network"


# --- market -------------------------------------------------------------------------------------


def ms(day: str) -> int:
    return int(datetime.fromisoformat(day).replace(tzinfo=UTC).timestamp() * 1000)


def market_api(broken: str | None = None) -> Fake:
    def route(method: str, url: str, data: bytes | None) -> tuple[int, bytes]:
        if broken and broken in url:
            return 503, b""
        if "frankfurter" in url:
            if "/latest" in url:
                return 200, b'{"date":"2026-10-27","rates":{"EUR":1.0625,"USD":1.25}}'
            body = {"rates": {"2026-10-26": {"EUR": 1.0625, "USD": 1.25}}}
            return 200, json.dumps(body).encode()
        if "coingecko" in url:
            pts = [[ms("2026-10-25T00:00"), 90000.5], [ms("2026-10-26T00:00"), 91000.25]]
            return 200, json.dumps({"prices": pts}).encode()
        if "yahoo" in url:
            chart = {
                "chart": {
                    "result": [
                        {
                            "meta": {"currency": "GBp"},
                            "timestamp": [ms("2026-10-26T08:00") // 1000],
                            "indicators": {"quote": [{"close": [8512.0]}]},
                        }
                    ]
                }
            }
            return 200, json.dumps(chart).encode()
        if "/txs/chain" in url:
            return 200, b"[]"
        if "etherscan" in url:
            return 200, b'{"status":"0","message":"No transactions found","result":[]}'
        if "mempool" in url:
            stats = {"funded_txo_sum": 150_000_000, "spent_txo_sum": 25_000_000}
            return 200, json.dumps({"chain_stats": stats}).encode()
        if "rpc" in url:
            assert data is not None
            assert json.loads(data)["method"] == "eth_getBalance"
            return 200, b'{"jsonrpc":"2.0","id":1,"result":"0x1bc16d674ec80000"}'
        raise AssertionError(url)

    return Fake(route)


WALLETS = {
    "wallets": [
        {"account": "crypto:froid", "asset": "BTC", "addresses": ["bc1qfictive1", "bc1qfictive2"]},
        {"account": "crypto:chaud", "asset": "ETH", "addresses": ["0x" + "fe" * 20]},
    ]
}


def test_market_check_reads_latest_rates(make_env: Any) -> None:
    env = make_env("market")
    fake = market_api()
    assert market.run(env, "check", Http(fake)).outcome == "ok"
    assert [u for _m, u in fake.calls] == [
        "https://api.frankfurter.dev/v1/latest?base=CHF&symbols=EUR%2CUSD%2CGBP"
    ]


def test_market_run_drops_a_file_the_finance_domain_reads(make_env: Any) -> None:
    cfg = {
        "quotes": {"GB00TEST0001": "TEST.L"},
        "crypto": {"BTC": "bitcoin", "ETH": "ethereum"},
        "erc20_tokens": {},
        "staking_tokens": {},
    }
    env = make_env("market", creds=WALLETS, market=cfg)
    fake = market_api()
    result = market.run(env, "run", Http(fake))
    assert (result.outcome, result.files, result.detail) == ("ok", 1, None)
    (raw,) = inbox_files(env)
    doc = market_file.parse(raw)
    assert [(x.base, x.rate) for x in doc.fx] == [
        ("EUR", Decimal("0.941176470588")),
        ("USD", Decimal("0.8")),
    ]
    assert [(p.key, p.on_date, p.price, p.currency) for p in doc.prices] == [
        ("CRYPTO:BTC", "2026-10-25", Decimal("90000.5"), "CHF"),
        ("CRYPTO:BTC", "2026-10-26", Decimal("91000.25"), "CHF"),
        ("CRYPTO:ETH", "2026-10-25", Decimal("90000.5"), "CHF"),
        ("CRYPTO:ETH", "2026-10-26", Decimal("91000.25"), "CHF"),
        ("GB00TEST0001", "2026-10-26", Decimal("85.12"), "GBP"),
    ]
    # deux adresses BTC additionnées (2 × 1.25), 2 ETH
    assert [(b.account, b.key, b.quantity) for b in doc.balances] == [
        ("crypto:froid", "CRYPTO:BTC", Decimal("2.5")),
        ("crypto:chaud", "CRYPTO:ETH", Decimal("2")),
    ]
    # un an d'historique au premier run, une semaine de recouvrement ensuite
    assert "days=365" in next(u for _m, u in fake.calls if "coingecko" in u)
    assert env.memory.get("last_run") == "2026-10-27"
    later = market_api()
    assert market.run(env, "run", Http(later)).outcome == "nothing_new"
    assert "days=8" in next(u for _m, u in later.calls if "coingecko" in u)


def test_market_follows_the_base_currency(make_env: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Un hub en euros : cours de change vers l'euro (le franc compris), cryptos en euros."""
    monkeypatch.setenv("HUB_CURRENCY", "EUR")
    env = make_env(
        "market", market={"crypto": {"BTC": "bitcoin"}, "erc20_tokens": {}, "staking_tokens": {}}
    )
    fake = market_api()
    assert market.run(env, "run", Http(fake)).outcome == "ok"
    fx_url = next(u for _m, u in fake.calls if "frankfurter" in u)
    assert parse_qs(urlsplit(fx_url).query) == {"base": ["EUR"], "symbols": ["USD,GBP,CHF"]}
    assert "vs_currency=eur" in next(u for _m, u in fake.calls if "coingecko" in u)
    doc = market_file.parse(inbox_files(env)[0])
    assert {x.quote for x in doc.fx} == {"EUR"}
    assert {p.currency for p in doc.prices} == {"EUR"}


def test_market_optional_source_down_keeps_the_rest(make_env: Any) -> None:
    env = make_env("market")
    result = market.run(env, "run", Http(market_api(broken="coingecko")))
    assert (result.outcome, result.detail) == ("ok", "partial crypto:site_unavailable")
    assert env.memory.get("last_run") is None  # la prochaine fenêtre reste d'un an
    with pytest.raises(Failure):
        market.run(make_env("market"), "run", Http(market_api(broken="frankfurter")))


def test_market_bad_wallet_secret(make_env: Any) -> None:
    creds = {"wallets": [{"account": "crypto:x", "asset": "DOGE", "addresses": ["D1"]}]}
    with pytest.raises(Failure) as exc:
        market.run(make_env("market", creds=creds), "run", Http(market_api()))
    assert exc.value.outcome == "auth_error"
