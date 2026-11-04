"""Primitifs réseau des sources publiques du marché : une requête polie (pause, reprise sur
429), les nombres (décimaux, texte), l'API mempool.space et les appels JSON-RPC (EVM, Solana).
Partagés par `flow` (soldes, cours), `history` (historiques sur chaîne) et `cosmos`.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from decimal import Decimal, InvalidOperation, localcontext
from typing import Any

from hub.collectors.base import Failure
from hub.collectors.http import Http
from hub.collectors.runtime import Env

WEI = Decimal(10) ** 18
SATS = Decimal(10) ** 8


def dec(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        d = Decimal(str(value))
    except InvalidOperation:
        return None
    return d if d.is_finite() and d > 0 else None


def text_of(d: Decimal) -> str:
    with localcontext() as ctx:
        ctx.prec = 12
        out = +d
    return format(out.normalize(), "f")


RETRY_PAUSES = (10, 30, 60)
sleep: Callable[[int], None] = time.sleep


def polite(
    http: Http, url: str, step: str, pause: int, read: Callable[[Any], Any] = lambda d: d, **kw: Any
) -> Any:
    """Une requête vers une source publique limitée (mempool.space, CoinGecko, historiques) :
    une pause avant, et sur un refus (429) une attente croissante avant de réessayer."""
    for retry in (*RETRY_PAUSES, 0):
        if pause:
            sleep(pause)
        try:
            return read(http.json(url, step, **kw))
        except Failure as f:
            if not retry or not f.detail.endswith(":http_429"):
                raise
            sleep(retry)
    raise AssertionError  # pragma: no cover (la dernière tentative relève l'échec)


def mempool(env: Env, http: Http, path: str, step: str = "wallet.btc") -> Any:
    url = f"{env.cfg.market.mempool_url}/address/{path}"
    return polite(http, url, step, env.cfg.market.mempool_pause_seconds)


def rpc(url: str, http: Http, step: str, method: str, params: list[Any]) -> Any:
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    doc = http.json(url, step, method="POST", body=body)
    if not isinstance(doc, dict) or "result" not in doc:
        raise Failure("site_unavailable", f"{step}:rpc")
    return doc["result"]


def scaled(raw: Any, places: int) -> Decimal:
    return Decimal(int(raw)) / (Decimal(10) ** places)


def uint(url: str, http: Http, step: str, contract: str, data: str) -> int:
    return int(
        str(rpc(url, http, step, "eth_call", [{"to": contract, "data": data}, "latest"])), 16
    )


QUOTE_KINDS = {"ETF": "fund", "MUTUALFUND": "fund", "EQUITY": "stock"}


def quote_kind(instrument_type: object, instrument: str) -> str:
    """Le type que la source donne (`instrumentType` de Yahoo) ; à défaut, le préfixe de l'ISIN
    (IE, LU : un fonds), faute de mieux (audit m13)."""
    found = QUOTE_KINDS.get(str(instrument_type or "").upper())
    if found is not None:
        return found
    return "fund" if instrument.upper().startswith(("IE", "LU")) else "stock"
