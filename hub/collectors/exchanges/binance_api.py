"""Le bas niveau de l'historique Binance : constantes, horodatages, une opération (`Op`) et
ses jambes, et les appels signés (`Api`) avec leurs pauses, leurs fenêtres coupées en deux
quand elles sont pleines, et les fenêtres refusées comptées et gardées (`gaps`), jamais tenues
pour lues (audit M15)."""

from __future__ import annotations

import time
from collections import defaultdict
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from hub.collectors.base import Failure
from hub.collectors.http import Http
from hub.collectors.runtime import Env

DAY_MS = 86_400_000
OVERLAP_DAYS = 3
FIAT = frozenset({"CHF", "EUR", "USD", "GBP", "TRY", "BRL", "AUD", "PLN", "RON", "UAH", "ZAR"})
STABLE = frozenset({"USDT", "USDC", "BUSD", "FDUSD", "TUSD", "USDP", "DAI"})
DEPOSIT_DONE = frozenset({1, 6})  # crédité (6 : crédité, pas encore retirable)
WITHDRAW_DONE = 6
MAX_PAGES = 50
EARN_DAYS = 29  # rewardsRecord : 30 jours au plus par appel (sinon -6021)


def _pause(ms: int) -> None:
    time.sleep(ms / 1000)


sleep: Callable[[int], None] = _pause  # en millisecondes ; remplacé dans les tests


def _ms(day: date) -> int:
    return int(datetime(day.year, day.month, day.day, tzinfo=UTC).timestamp()) * 1000


def _day(ms: Any) -> str:
    return datetime.fromtimestamp(int(ms) // 1000, UTC).date().isoformat()


def _qty(value: Any) -> Decimal:
    try:
        d = Decimal(str(value))
    except InvalidOperation:
        raise Failure("invalid_file", "binance.history") from None
    if not d.is_finite():
        raise Failure("invalid_file", "binance.history")
    return d


def _text(d: Decimal) -> str:
    out = format(d.normalize(), "f")
    return "0" if out in ("-0", "") else out


@dataclass
class Op:
    id: str
    kind: str
    on_date: str
    legs: list[tuple[str, Decimal, str]] = field(default_factory=list)  # actif, quantité, rôle
    txid: str = ""
    address: str = ""
    network: str = ""
    # contre-valeur donnée par la plateforme (Coinbase : `native_amount`), par jambe
    values: dict[int, tuple[Decimal, str]] = field(default_factory=dict)

    def leg(
        self, asset: Any, quantity: Decimal, role: str, value: tuple[Decimal, str] | None = None
    ) -> Op:
        if quantity:
            if value is not None:
                self.values[len(self.legs)] = value
            self.legs.append((str(asset).upper(), quantity, role))
        return self

    def doc(self, account: str) -> dict[str, Any]:
        legs = []
        for i, (a, q, r) in enumerate(self.legs):
            leg: dict[str, str] = {"instrument": a, "quantity": _text(q), "role": r}
            if i in self.values:
                leg["value"], leg["value_currency"] = _text(self.values[i][0]), self.values[i][1]
            legs.append(leg)
        out: dict[str, Any] = {
            "account": account,
            "id": self.id,
            "kind": self.kind,
            "on_date": self.on_date,
            "legs": legs,
        }
        for k in ("txid", "address", "network"):
            if getattr(self, k):
                out[k] = getattr(self, k)[:128]
        return out


class Api:
    """Appels signés de l'historique : pause entre deux appels, une reprise après un 429, et
    les fenêtres refusées (400 : trop anciennes pour ce flux) comptées plutôt que fatales."""

    def __init__(self, env: Env, http: Http, call: Callable[..., Any]) -> None:
        self.env = env
        self.http = http
        self.call = call
        self.skipped: dict[str, int] = defaultdict(int)
        # fenêtres refusées par flux (ms, 0 = jusqu'à aujourd'hui) : jamais tenues pour lues
        self.gaps: dict[str, list[tuple[int, int]]] = defaultdict(list)

    def get(self, path: str, step: str, params: dict[str, Any], pause: int = 0) -> Any:
        pause = pause or self.env.cfg.exchanges.history_pause_ms
        for attempt in (0, 1):
            if pause:
                sleep(pause)
            try:
                return self.call(self.env, self.http, path, step, params)
            except Failure as f:
                if f.detail.endswith(":http_429") and not attempt:
                    sleep(60_000)
                    continue
                if f.detail.endswith(":http_400"):
                    self.skipped[step] += 1
                    return None
                raise
        return None  # pragma: no cover - la boucle rend toujours

    def windows(
        self,
        path: str,
        step: str,
        start: int,
        end: int,
        span_days: int,
        rows_of: Callable[[Any], list[Any] | None],
        *,
        limit: int,
        params: dict[str, Any] | None = None,
        pause: int = 0,
        keys: tuple[str, str] = ("startTime", "endTime"),
    ) -> Iterator[Any]:
        """Lignes de toutes les fenêtres [start, end] ; une fenêtre pleine est coupée en deux."""
        cursor = start
        while cursor < end:
            stop = min(cursor + span_days * DAY_MS, end)
            yield from self._window(path, step, cursor, stop, rows_of, limit, params, pause, keys)
            cursor = stop + 1

    def _window(
        self,
        path: str,
        step: str,
        start: int,
        end: int,
        rows_of: Callable[[Any], list[Any] | None],
        limit: int,
        params: dict[str, Any] | None,
        pause: int,
        keys: tuple[str, str],
    ) -> Iterator[Any]:
        doc = self.get(path, step, {**(params or {}), keys[0]: start, keys[1]: end}, pause)
        if doc is None:
            self.gaps[step].append((start, end))
            return
        rows = rows_of(doc)
        if rows is None:
            raise Failure("invalid_file", step)
        if len(rows) >= limit and end - start > 60_000:
            middle = (start + end) // 2
            args = (rows_of, limit, params, pause, keys)
            yield from self._window(path, step, start, middle, *args)
            yield from self._window(path, step, middle + 1, end, *args)
            return
        yield from rows


def _list(doc: Any) -> list[Any] | None:
    return doc if isinstance(doc, list) else None


def _rows(doc: Any) -> list[Any] | None:
    rows = doc.get("rows") if isinstance(doc, dict) else None
    return rows if isinstance(rows, list) else ([] if isinstance(doc, dict) else None)


def _data(doc: Any) -> list[Any] | None:
    rows = doc.get("data") if isinstance(doc, dict) else None
    return rows if isinstance(rows, list) else ([] if isinstance(doc, dict) else None)
