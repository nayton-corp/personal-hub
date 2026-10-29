"""Collecteur Binance : comptes Spot et Funding, Simple Earn (flexible et bloqué), par l'API
officielle signée HMAC-SHA256, et l'historique des opérations (`binance_history`). Clé avec
« Enable Reading » seulement."""

from __future__ import annotations

import hashlib
import hmac
import urllib.parse
from collections.abc import Iterator
from typing import Any

from hub.collectors.base import Failure
from hub.collectors.exchanges import binance_history
from hub.collectors.exchanges.common import now_ms, runner
from hub.collectors.http import Http
from hub.collectors.runtime import Env

MAX_PAGES = 10


def signed(
    env: Env,
    http: Http,
    path: str,
    step: str,
    params: dict[str, Any] | None = None,
    method: str = "GET",
) -> Any:
    query = urllib.parse.urlencode({**(params or {}), "recvWindow": 10_000, "timestamp": now_ms()})
    sign = hmac.new(env.secret("api_secret").encode(), query.encode(), hashlib.sha256)
    url = f"{env.cfg.exchanges.binance_url}{path}?{query}&signature={sign.hexdigest()}"
    return http.json(url, step, method=method, headers={"X-MBX-APIKEY": env.secret("api_key")})


def _earn(env: Env, http: Http, kind: str, field: str) -> Iterator[tuple[str, Any]]:
    seen = 0
    for page in range(1, MAX_PAGES + 1):
        doc = signed(
            env,
            http,
            f"/sapi/v1/simple-earn/{kind}/position",
            f"binance.earn_{kind}",
            {"current": page, "size": 100},
        )
        rows = doc.get("rows") if isinstance(doc, dict) else None
        if not isinstance(rows, list):
            raise Failure("invalid_file", f"binance.earn_{kind}")
        for r in rows:
            yield r["asset"], r[field]
        seen += len(rows)
        if not rows or seen >= int(doc.get("total") or 0):
            return


def fetch(env: Env, http: Http) -> list[tuple[str, Any]]:
    try:
        flexible = list(_earn(env, http, "flexible", "totalAmount"))
        locked = list(_earn(env, http, "locked", "amount"))
        spot = signed(env, http, "/api/v3/account", "binance.spot", {"omitZeroBalances": "true"})
        funding = signed(
            env, http, "/sapi/v1/asset/get-funding-asset", "binance.funding", method="POST"
        )
        earned = {str(a) for a, _q in flexible}
        out = flexible + locked
        for b in spot["balances"]:
            asset = str(b["asset"])
            # ancienne épargne flexible : « LDBTC » double le BTC de Simple Earn
            if asset.startswith("LD") and asset[2:] in earned:
                continue
            out += [(asset, b["free"]), (asset, b["locked"])]
        for b in funding:
            out += [(b["asset"], b[k]) for k in ("free", "locked", "freeze", "withdrawing")]
    except (KeyError, TypeError):
        raise Failure("invalid_file", "binance.balances") from None
    return out


def history(env: Env, http: Http, account: str, held: set[str]) -> binance_history.History:
    return binance_history.collect(env, http, signed, account, held)


run = runner(fetch, history)
