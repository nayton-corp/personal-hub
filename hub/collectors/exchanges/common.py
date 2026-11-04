"""Ce que les collecteurs de plateformes crypto partagent : un run qui lit les soldes par l'API
officielle (clé en lecture seule) et dépose un `hub.market.v1` avec ces soldes, et, pour une
plateforme qui sait lire son historique (Binance), ses opérations et leurs cours.

Les soldes deviennent un relevé de positions du compte `crypto:<plateforme>` (à déclarer avec
`fin crypto add-wallet <plateforme>`, ou le champ `account` des secrets). La valeur, dans la
devise de base, vient des cours CoinGecko du collecteur « market », et pour les autres cryptos
détenues des clôtures Binance des derniers jours, relues à chaque passage ; une crypto sans
cours est signalée (run incomplet) et attend son premier cours.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable, Iterable
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from hub.collectors.base import Failure, Kind, Result
from hub.collectors.dropbox import is_market_json
from hub.collectors.exchanges.binance_api import FIAT, STABLE
from hub.collectors.http import Http
from hub.collectors.market.flow import binance_prices, holdings
from hub.collectors.runtime import Env

Fetch = Callable[[Env, Http], Iterable[tuple[str, Any]]]
# (env, http, compte, actifs détenus) → opérations, cours, flux en échec, mémoire à garder
History = Callable[[Env, Http, str, set[str]], Any]
_ACCOUNT = re.compile(r"^crypto:[a-z0-9][a-z0-9-]{0,40}$")
_SYMBOL = re.compile(r"^[A-Z0-9]{1,20}$")
RECENT_DAYS = 7  # clôtures relues à chaque passage : un jour manqué se rattrape


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


def recent_prices(
    env: Env, http: Http, held: dict[str, Decimal]
) -> tuple[list[dict[str, str]], list[str]]:
    """Clôtures Binance des derniers jours de chaque crypto détenue que CoinGecko ne suit pas
    (collecteur « market ») : sans elles, la crypto garde le cours de sa dernière opération, ou
    n'en a aucun. Une crypto sans paire USDT est dite (`prices.<symbole>:no_pair`)."""
    covered = set(env.cfg.market.crypto) | FIAT | STABLE
    start, end = env.today - timedelta(days=RECENT_DAYS), env.today + timedelta(days=1)
    rows: list[dict[str, str]] = []
    notes: list[str] = []
    for symbol in sorted(s for s, q in held.items() if q > 0 and s not in covered):
        try:
            rows += binance_prices(env, http, [symbol], start, end)
        except Failure as f:
            no_pair = f.detail.endswith(":http_400")
            notes.append(f"prices.{symbol.lower()}:{'no_pair' if no_pair else f.outcome}")
            continue
        if not any(r["instrument"] == symbol for r in rows):
            notes.append(f"prices.{symbol.lower()}:no_pair")
    return rows, notes


def runner(fetch: Fetch, history: History) -> Callable[..., Result]:
    """Le run d'une plateforme : ses soldes ET son historique (règle du hub : pas de connecteur
    crypto sans écritures au Journal ; `tests/collectors/test_crypto_history_rule.py`)."""

    def run(env: Env, kind: Kind, http: Http | None = None) -> Result:
        http = http or Http()
        account = str(env.creds.get("account") or f"crypto:{env.name}")
        if not _ACCOUNT.match(account):
            raise Failure("auth_error", "secret:account")
        held = totals(env, fetch(env, http), f"{env.name}.balances")
        if kind == "check":
            return Result("ok")
        doc: dict[str, Any] = {
            "format": "hub.market.v1",
            "fetched_at": env.today.isoformat(),
            "balances": holdings(account, env.today, held, "BTC"),
        }
        past = history(env, http, account, set(held))
        recent, missing = recent_prices(env, http, held)
        doc.update(operations=past.operations, prices=past.prices + recent, fx=past.fx)
        doc["gaps"] = list(getattr(past, "gaps", []))
        data = json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()
        dropped = env.inbox.drop(f"{env.name}.json", data, is_market_json, step=f"{env.name}.file")
        past.commit()
        gaps = past.failed + missing
        detail = "partial " + " ".join(gaps) if gaps else None
        return Result("ok" if dropped else "nothing_new", int(dropped), detail)

    run.history = history  # type: ignore[attr-defined]
    return run
