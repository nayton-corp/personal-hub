"""Historique d'une plateforme lu par son API (Coinbase, KuCoin), sur le modèle de Binance
(`binance_history`) : chaque passage dépose les opérations, leurs cours et, au premier
passage, le change BCE ; le premier passage est complet ou ne dépose rien ; ensuite, quelques
jours de recouvrement (mémoire `history_since`)."""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

from hub.collectors.base import Failure
from hub.collectors.exchanges.binance_history import OVERLAP_DAYS, History, Op, _price_rows
from hub.collectors.http import Http
from hub.collectors.market.flow import fx_rates
from hub.collectors.runtime import Env

# (env, http, premier jour à lire ou None pour tout) → opérations, flux à signaler
Reader = Callable[[Env, Http, date | None], tuple[list[Op], list[str]]]


def _pause(ms: int) -> None:
    time.sleep(ms / 1000)


sleep: Callable[[int], None] = _pause  # en millisecondes ; remplacé dans les tests


def pause(env: Env) -> None:
    if env.cfg.exchanges.history_pause_ms:
        sleep(env.cfg.exchanges.history_pause_ms)


def collect(env: Env, http: Http, account: str, read: Reader) -> History:
    memory = env.memory
    since = memory.get("history_since")
    full = since is None
    start = None if full else date.fromisoformat(since) - timedelta(days=OVERLAP_DAYS)
    failed: list[str] = []
    try:
        ops, notes = read(env, http, start)
        failed += notes
    except Failure as f:
        if f.outcome == "auth_error":
            raise
        ops = []
        failed.append(f"history:{f.outcome}")
    except (KeyError, TypeError, ValueError):
        ops = []
        failed.append("history:invalid_file")
    prices = _price_rows(env, http, ops, failed) if ops else []
    fx: list[dict[str, Any]] = []
    if full and ops:
        try:
            first = date.fromisoformat(min(op.on_date for op in ops))
            fx = fx_rates(env, http, first, until=env.today)
        except Failure as f:
            failed.append(f"fx:{f.outcome}")
    broken = [f for f in failed if "skipped=" not in f]
    if full and broken:
        ops, prices, fx = [], [], []
    ops.sort(key=lambda op: (op.on_date, op.id))

    def commit() -> None:
        if not broken:
            memory.put("history_since", env.today.isoformat())

    return History([op.doc(account) for op in ops], prices, fx, failed, commit)
