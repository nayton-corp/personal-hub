"""Ce que les collecteurs de plateformes crypto partagent : un run qui lit les soldes par l'API
officielle (clé en lecture seule) et dépose un `hub.market.v1` avec ces soldes seulement.

Les soldes deviennent un relevé de positions du compte `crypto:<plateforme>` (à déclarer avec
`fin crypto add-wallet <plateforme>`, ou le champ `account` des secrets). La valeur en CHF vient
des cours CoinGecko du collecteur « market » ; une crypto sans cours y attend son premier cours.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable, Iterable
from decimal import Decimal, InvalidOperation
from typing import Any

from hub.collectors.base import Failure, Kind, Result
from hub.collectors.dropbox import is_market_json
from hub.collectors.http import Http
from hub.collectors.market.flow import holdings
from hub.collectors.runtime import Env

Fetch = Callable[[Env, Http], Iterable[tuple[str, Any]]]
_ACCOUNT = re.compile(r"^crypto:[a-z0-9][a-z0-9-]{0,40}$")
_SYMBOL = re.compile(r"^[A-Z0-9]{1,20}$")


def now_ms() -> int:
    return time.time_ns() // 1_000_000


def amount(value: Any, step: str) -> Decimal:
    try:
        d = Decimal(str(value))
    except InvalidOperation:
        raise Failure("invalid_file", step) from None
    if not d.is_finite():
        raise Failure("invalid_file", step)
    return d


def totals(env: Env, items: Iterable[tuple[str, Any]], step: str) -> dict[str, Decimal]:
    """Somme par symbole (alias appliqués) ; un symbole hors format est ignoré."""
    aliases = env.cfg.exchanges.aliases
    out: dict[str, Decimal] = {}
    for symbol, value in items:
        s = str(symbol).upper()
        s = aliases.get(s, s)
        if _SYMBOL.match(s):
            out[s] = out.get(s, Decimal(0)) + amount(value, step)
    return out


def runner(fetch: Fetch) -> Callable[..., Result]:
    def run(env: Env, kind: Kind, http: Http | None = None) -> Result:
        http = http or Http()
        account = str(env.creds.get("account") or f"crypto:{env.name}")
        if not _ACCOUNT.match(account):
            raise Failure("auth_error", "secret:account")
        held = totals(env, fetch(env, http), f"{env.name}.balances")
        if kind == "check":
            return Result("ok")
        doc = {
            "format": "hub.market.v1",
            "fetched_at": env.today.isoformat(),
            "balances": holdings(account, env.today, held, "BTC"),
        }
        data = json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()
        dropped = env.inbox.drop(f"{env.name}.json", data, is_market_json, step=f"{env.name}.file")
        return Result("ok" if dropped else "nothing_new", int(dropped))

    return run
