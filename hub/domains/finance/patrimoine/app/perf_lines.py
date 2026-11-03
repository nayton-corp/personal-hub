"""Construction de la série du patrimoine (model/engine.py) depuis la base — comptes, écritures
du jour, parts et cours, dettes, opérations crypto — et sa mémoire : la série est gardée tant que
l'empreinte du registre, des cours, du change, des dettes et des décisions n'a pas changé,
attachée au moteur SQLAlchemy du domaine (elle part avec lui), gelée (audit m4)."""

from __future__ import annotations

import threading
import weakref
from typing import Any

from sqlalchemy import Connection, text
from sqlalchemy import Engine as SqlEngine

from hub.domains.finance.patrimoine.app import crypto_cost, debts, decisions, ledger_sums
from hub.domains.finance.patrimoine.app.market_data import FxTable, Positions
from hub.domains.finance.patrimoine.model import engine
from hub.kernel.money import base_currency

ABSENT = engine.ABSENT
Engine = engine.Series
Line = engine.Line


class _Debt:
    """Une dette vue par la série (engine.Liability), calculée par debts.Book."""

    def __init__(self, book: debts.Book, debt: debts.Debt) -> None:
        self.key = debts.key(debt.id)
        self.currency = debt.currency
        self._book, self._debt = book, debt
        self._paid = dict(book.paid.get(debt.id, []))

    def balance(self, on: str) -> int | None:
        return self._book.balance(self._debt, on)

    def paid(self, on: str) -> int | None:
        return self._paid.get(on)


def _first_day(conn: Connection, as_of: str) -> str | None:
    days = []
    for table, col in (
        ("entries", "booking_date"),
        ("trades", "trade_date"),
        ("holdings", "on_date"),
        ("debt_balance_records", "on_date"),
    ):
        d = conn.execute(text(f"SELECT min({col}) FROM {table}")).scalar_one()  # noqa: S608
        if d is None or d > as_of:
            continue
        days.append(d)
    return min(days) if days else None


def accounts(conn: Connection) -> tuple[engine.Account, ...]:
    rows = conn.execute(
        text(
            "SELECT id, kind, currency, liquid, hidden FROM accounts ORDER BY institution, name, id"
        )
    ).fetchall()
    return tuple(engine.Account(r[0], r[1], r[2], bool(r[3]), bool(r[4])) for r in rows)


def inputs(conn: Connection, as_of: str) -> engine.Inputs | None:
    """Tout ce que la série lit, lu une fois ; None sans aucune donnée jusqu'à `as_of`."""
    first = _first_day(conn, as_of)
    if first is None:
        return None
    fx = FxTable(conn)
    positions = Positions(conn, fx)
    accts = accounts(conn)
    moves: dict[str, dict[str, engine.Moves]] = {}
    for on, acc, total, inc, fee, dep in conn.execute(text(ledger_sums.DAILY_SQL), {"d": as_of}):
        moves.setdefault(acc, {})[on] = (int(total), int(inc), int(fee), int(dep))
    book = debts.Book.read(conn)
    # flux des cryptos tirés des opérations (politique de calcul) : coût, récompense sans apport
    flows: engine.Flows = {}
    if any(a.kind == "crypto" for a in accts):
        flows = crypto_cost.walk(conn, as_of, fx, decisions.lots(decisions.read(conn))).flows
    return engine.Inputs(
        engine.days(first, as_of),
        base_currency(),
        accts,
        moves,
        positions,
        [_Debt(book, d) for d in book.debts],
        flows,
    )


def build(conn: Connection, as_of: str) -> engine.Series | None:
    inp = inputs(conn, as_of)
    return None if inp is None else engine.build(inp)


_LOCK = threading.Lock()
_CACHE: weakref.WeakKeyDictionary[SqlEngine, tuple[tuple[Any, ...], engine.Series | None]] = (
    weakref.WeakKeyDictionary()
)
_FINGERPRINT = (
    "SELECT (SELECT coalesce(max(rowid), 0) || '/' || count(*) FROM entries), "
    "(SELECT coalesce(max(rowid), 0) || '/' || count(*) FROM categorizations), "
    "(SELECT coalesce(max(rowid), 0) || '/' || count(*) FROM trades), "
    "(SELECT coalesce(max(rowid), 0) || '/' || count(*) FROM holdings), "
    "(SELECT coalesce(max(rowid), 0) || '/' || count(*) FROM prices), "
    "(SELECT coalesce(max(rowid), 0) || '/' || count(*) FROM fx_rates), "
    "(SELECT coalesce(max(rowid), 0) || '/' || count(*) FROM debt_balance_records), "
    "(SELECT coalesce(max(seq), 0) FROM events), "
    "(SELECT coalesce(max(rowid), 0) || '/' || count(*) FROM reconcile_decisions), "
    "(SELECT coalesce(max(rowid), 0) || '/' || count(*) FROM reconcile_withdrawals), "
    "(SELECT group_concat(id || ':' || hidden || ':' || liquid) FROM accounts)"
)


def engine_for(conn: Connection, as_of: str) -> engine.Series | None:
    """La série jusqu'à `as_of`, de la mémoire si rien n'a changé et qu'elle va au moins
    jusque-là (une série plus longue vaut pour une date antérieure : chaque jour ne dépend que
    des précédents)."""
    stamp = tuple(conn.execute(text(_FINGERPRINT)).one())
    with _LOCK:
        hit = _CACHE.get(conn.engine)
        if hit is not None and hit[0] == stamp:
            found = hit[1]
            if found is None or found.days[-1] >= as_of:
                return found
    eng = build(conn, as_of)
    with _LOCK:
        _CACHE[conn.engine] = (stamp, eng)
    return eng
