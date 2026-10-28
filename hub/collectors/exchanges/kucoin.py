"""Collecteur KuCoin : tous les comptes (main, trade, marge…) et les placements Earn, par l'API
officielle (signature HMAC-SHA256, clé v2). Clé avec la permission « General » seulement."""

from __future__ import annotations

import base64
import hashlib
import hmac
from typing import Any

from hub.collectors.base import Failure
from hub.collectors.exchanges.common import now_ms, runner
from hub.collectors.http import Http
from hub.collectors.runtime import Env

MAX_PAGES = 10
AUTH_CODES = {"400001", "400002", "400003", "400004", "400005", "400006", "400007", "411100"}


def _sign(secret: str, message: str) -> str:
    digest = hmac.new(secret.encode(), message.encode(), hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


def get(env: Env, http: Http, path: str, step: str) -> Any:
    secret = env.secret("api_secret")
    stamp = str(now_ms())
    headers = {
        "KC-API-KEY": env.secret("api_key"),
        "KC-API-SIGN": _sign(secret, stamp + "GET" + path),
        "KC-API-TIMESTAMP": stamp,
        "KC-API-PASSPHRASE": _sign(secret, env.secret("passphrase")),
        "KC-API-KEY-VERSION": "2",
    }
    doc = http.json(f"{env.cfg.exchanges.kucoin_url}{path}", step, headers=headers)
    code = str(doc.get("code")) if isinstance(doc, dict) else ""
    if code in AUTH_CODES:
        raise Failure("auth_error", f"{step}:{code}")
    if code != "200000":
        raise Failure("site_unavailable", f"{step}:code")
    return doc.get("data")


def fetch(env: Env, http: Http) -> list[tuple[str, Any]]:
    try:
        out = [
            (a["currency"], a["balance"])
            for a in get(env, http, "/api/v1/accounts", "kucoin.accounts")
        ]
        for page in range(1, MAX_PAGES + 1):
            path = f"/api/v1/earn/hold-assets?currentPage={page}&pageSize=50"
            data = get(env, http, path, "kucoin.earn")
            out += [(a["currency"], a["holdAmount"]) for a in data["items"]]
            if page >= int(data.get("totalPage") or 1):
                break
    except (KeyError, TypeError):
        raise Failure("invalid_file", "kucoin.balances") from None
    return out


run = runner(fetch)
