"""Lignes de la performance (voir performance.py) : chaque instrument d'un compte à positions,
solde de compte ou dette, avec sa valeur et son flux de chaque jour depuis la première écriture,
calculés une fois et gardés en mémoire tant que l'empreinte du registre, des cours, du change et
des dettes n'a pas changé."""

from __future__ import annotations

import threading
from array import array
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal, localcontext
from typing import Any

from sqlalchemy import Connection, text

from hub.domains.finance.patrimoine.app import debts, valuation
from hub.domains.finance.registre.model import institutions
from hub.kernel.money import DECIMAL_CONTEXT, base_currency

INCOME_CATEGORIES = ("rendement", "interets-dividendes")
FEE_CATEGORIES = ("frais-placement",)
_INCOME_CODES = tuple(c.prefix for c in institutions.CODES if c.category in INCOME_CATEGORIES)
_FEE_CODES = tuple(c.prefix for c in institutions.CODES if c.category in FEE_CATEGORIES)


def _in(cats: tuple[str, ...]) -> str:
    return ", ".join(f"'{c}'" for c in cats)  # identifiants fixes, jamais une saisie


INCOME_SQL = (
    f"CASE WHEN vc.category_id IN ({_in(INCOME_CATEGORIES)}) OR "
    f"{institutions.like_any('e.bank_tx_code', _INCOME_CODES)} THEN e.amount_minor ELSE 0 END"
)
FEES_SQL = (
    f"CASE WHEN vc.category_id IN ({_in(FEE_CATEGORIES)}) OR "
    f"{institutions.like_any('e.bank_tx_code', _FEE_CODES)} THEN e.amount_minor ELSE 0 END"
)


@dataclass
class Line:
    id: str  # "<compte>|<instrument>", "<compte>|cash" ou "debt:<id>"
    account_id: str  # le compte, ou la clé de la dette
    asset: str  # "isin:<instrument>", "ccy:<devise>" ou "debt:<id>" (vue Actifs de l'app)
    kind: str  # "position" | "cash" | "debt"
    hidden: bool
    n: int
    value: array[int] = field(init=False)  # centimes ; ABSENT hors du patrimoine ce jour-là
    flow: array[int] = field(init=False)
    income: array[int] = field(init=False)
    fees: array[int] = field(init=False)
    missing: bytearray = field(init=False)  # 1 : aurait une valeur, mais pas de cours ou change

    def __post_init__(self) -> None:
        self.value = array("q", [ABSENT]) * self.n
        self.flow = array("q", [0]) * self.n
        self.income = array("q", [0]) * self.n
        self.fees = array("q", [0]) * self.n
        self.missing = bytearray(self.n)


ABSENT = -(2**63)


@dataclass
class Engine:
    days: list[str]
    lines: dict[str, Line]
    currency: str
    banks: frozenset[str] = frozenset()  # comptes bancaires (type « cash ») : salaire et dépenses

    def index(self, on: str) -> int:
        """Indice du jour `on`, borné à la série."""
        if on <= self.days[0]:
            return 0
        if on >= self.days[-1]:
            return len(self.days) - 1
        return (date.fromisoformat(on) - date.fromisoformat(self.days[0])).days

    def default_ids(self) -> list[str]:
        """Les lignes de l'app : comptes non masqués et dettes."""
        return [i for i, ln in self.lines.items() if not ln.hidden]


def _first_day(conn: Connection, as_of: str) -> str | None:
    found = [
        conn.execute(text(f"SELECT min({col}) FROM {table}")).scalar_one()  # noqa: S608
        for table, col in (
            ("entries", "booking_date"),
            ("trades", "trade_date"),
            ("holdings", "on_date"),
            ("debt_balances", "on_date"),
        )
    ]
    days = [d for d in found if d is not None and d <= as_of]
    return min(days) if days else None


def _days(first: str, last: str) -> list[str]:
    d, end = date.fromisoformat(first), date.fromisoformat(last)
    out = []
    while d <= end:
        out.append(d.isoformat())
        d += timedelta(days=1)
    return out


@dataclass
class _Holding:
    """Parts d'un compte à positions, tenues jour après jour comme Positions.quantities."""

    reports: list[tuple[str, dict[str, tuple[Decimal, int, str]]]]
    trades: list[tuple[str, str, Decimal]]
    ri: int = 0
    ti: int = 0
    qty: dict[str, Decimal] = field(default_factory=dict)
    base: dict[str, tuple[Decimal, int, str]] = field(default_factory=dict)
    since: str = ""
    moved: set[str] = field(default_factory=set)

    def advance(self, on: str) -> None:
        while self.ti < len(self.trades) and self.trades[self.ti][0] <= on:
            d, isin, q = self.trades[self.ti]
            if self.since < d:
                self.qty[isin] = self.qty.get(isin, Decimal(0)) + q
                self.moved.add(isin)
            self.ti += 1
        while self.ri < len(self.reports) and self.reports[self.ri][0] <= on:
            self.since, self.base = self.reports[self.ri]
            self.qty = {isin: q for isin, (q, _v, _c) in self.base.items()}
            self.moved = set()
            self.ri += 1


def _unit_values(
    h: _Holding, positions: valuation.Positions, on: str
) -> dict[str, tuple[Decimal, int | None]]:
    """{instrument: (parts, valeur en centimes ou None sans cours)}, comme Positions.lines."""
    out: dict[str, tuple[Decimal, int | None]] = {}
    fx = positions.fx
    with localcontext(DECIMAL_CONTEXT):
        for isin, q in h.qty.items():
            if q == 0:
                continue
            known = positions.price(isin, on)
            if known is None:
                out[isin] = (q, None)
                continue
            d, price, ccy = known
            if isin in h.base and isin not in h.moved and d == h.since:
                _q, reported, rccy = h.base[isin]
                out[isin] = (q, fx.to_base(reported, rccy, on))
            else:
                out[isin] = (q, fx.convert(q * price, ccy, on))
    return out


def build(conn: Connection, as_of: str) -> Engine | None:
    first = _first_day(conn, as_of)
    if first is None:
        return None
    days = _days(first, as_of)
    n = len(days)
    ccy = base_currency()
    fx = valuation.FxTable(conn)
    positions = valuation.Positions(conn, fx)
    book = debts.Book.read(conn)
    accts = conn.execute(
        text("SELECT id, kind, currency, hidden FROM accounts ORDER BY institution, name, id")
    ).fetchall()
    # écritures du jour par compte : total, revenus, frais (centimes de la devise du compte)
    daily: dict[str, dict[str, tuple[int, int, int]]] = {}
    for on, acc, total, inc, fee in conn.execute(
        text(
            f"SELECT e.booking_date, e.account_id, sum(e.amount_minor), sum({INCOME_SQL}), "  # noqa: S608
            f"sum({FEES_SQL}) FROM entries e {valuation.CATEGORY_JOIN} "
            "WHERE e.booking_date <= :d GROUP BY e.booking_date, e.account_id"
        ),
        {"d": as_of},
    ):
        daily.setdefault(acc, {})[on] = (int(total), int(inc), int(fee))

    lines: dict[str, Line] = {}

    def conv(minor: int, currency: str, on: str) -> int | None:
        return 0 if minor == 0 else fx.to_base(minor, currency, on)

    def line(id_: str, account_id: str, asset: str, kind: str, hidden: bool) -> Line:
        if id_ not in lines:
            lines[id_] = Line(id_, account_id, asset, kind, hidden, n)
        return lines[id_]

    for acc_id, _kind, acc_ccy, hidden in accts:
        hidden = bool(hidden)
        moves = daily.get(acc_id, {})
        cash = line(f"{acc_id}|cash", acc_id, f"ccy:{acc_ccy}", "cash", hidden)
        holding = (
            _Holding(positions.reports.get(acc_id, []), positions.trades.get(acc_id, []))
            if acc_id in positions.accounts
            else None
        )
        balance = 0
        prev_q: dict[str, Decimal] = {}
        for k, on in enumerate(days):
            total, inc, fee = moves.get(on, (0, 0, 0))
            balance += total
            values: dict[str, tuple[Decimal, int | None]] = {}
            if holding is not None:
                holding.advance(on)
                values = _unit_values(holding, positions, on)
            # sans aucun cours, le compte garde son solde au registre (valuation.held)
            fallback = holding is None or not values or all(v is None for _q, v in values.values())
            if fallback:
                if holding is not None and not values and balance == 0:
                    pass  # compte à positions vide : hors du patrimoine
                else:
                    v = conv(balance, acc_ccy, on)
                    if v is None:
                        cash.missing[k] = 1
                    else:
                        cash.value[k] = v
                        inside = conv(total - inc - fee, acc_ccy, on)
                        cash.flow[k] = inside if inside is not None else 0
                        cash.income[k] = conv(inc, acc_ccy, on) or 0
                        cash.fees[k] = conv(fee, acc_ccy, on) or 0
                        # des parts sans aucun cours : valeur approchée par le registre
                        if values:
                            cash.missing[k] = 1
            else:
                # revenus et frais du compte à positions : déjà dans la valeur des parts, gardés
                # pour décomposer le gain ; la ligne « cash » n'a pas de valeur ici
                cash.income[k] = conv(inc, acc_ccy, on) or 0
                cash.fees[k] = conv(fee, acc_ccy, on) or 0
                for isin, (q, value) in values.items():
                    ln = line(f"{acc_id}|{isin}", acc_id, f"isin:{isin}", "position", hidden)
                    if value is None:
                        ln.missing[k] = 1
                        continue
                    ln.value[k] = value
                    dq = q - prev_q.get(isin, Decimal(0))
                    if dq:
                        with localcontext(DECIMAL_CONTEXT):
                            ln.flow[k] = int((Decimal(value) * dq / q).to_integral_value())
                # parts vendues jusqu'à zéro : la ligne vaut 0, la vente est un flux
                for isin in prev_q:
                    if isin in values:
                        continue
                    sold = lines.get(f"{acc_id}|{isin}")
                    if sold is None or k == 0 or sold.value[k - 1] == ABSENT:
                        continue
                    sold.value[k] = 0
                    sold.flow[k] = -sold.value[k - 1]
            prev_q = {isin: q for isin, (q, _v) in values.items()}

    for d in book.debts:
        ln = line(debts.key(d.id), debts.key(d.id), debts.key(d.id), "debt", False)
        paid = dict(book.paid.get(d.id, []))
        for k, on in enumerate(days):
            b = book.balance(d, on)
            if b is None:
                continue
            v = fx.to_base(b, d.currency, on)
            if v is None:
                ln.missing[k] = 1
                continue
            ln.value[k] = -v
            if on in paid:
                ln.flow[k] = fx.to_base(paid[on], d.currency, on) or 0

    # entrées et sorties du patrimoine : le saut est un flux, jamais un effet marché
    for ln in lines.values():
        prev = ABSENT
        for k in range(n):
            cur = ln.value[k]
            if prev == ABSENT and cur != ABSENT:
                ln.flow[k] = cur
                ln.income[k] = ln.fees[k] = 0
            elif prev != ABSENT and cur == ABSENT:
                ln.flow[k] = -prev
            elif cur == ABSENT:
                ln.flow[k] = 0
            prev = cur
    banks = frozenset(a[0] for a in accts if a[1] == "cash")
    return Engine(days, {i: ln for i, ln in lines.items() if _used(ln)}, ccy, banks)


def _used(ln: Line) -> bool:
    return any(v != ABSENT for v in ln.value) or any(ln.missing) or any(ln.income) or any(ln.fees)


_LOCK = threading.Lock()
_CACHE: dict[str, tuple[tuple[Any, ...], Engine | None]] = {}
_FINGERPRINT = (
    "SELECT (SELECT coalesce(max(rowid), 0) || '/' || count(*) FROM entries), "
    "(SELECT coalesce(max(rowid), 0) || '/' || count(*) FROM categorizations), "
    "(SELECT coalesce(max(rowid), 0) || '/' || count(*) FROM trades), "
    "(SELECT coalesce(max(rowid), 0) || '/' || count(*) FROM holdings), "
    "(SELECT coalesce(max(rowid), 0) || '/' || count(*) FROM prices), "
    "(SELECT coalesce(max(rowid), 0) || '/' || count(*) FROM fx_rates), "
    "(SELECT coalesce(max(rowid), 0) || '/' || count(*) FROM debt_balances), "
    "(SELECT coalesce(max(seq), 0) FROM events), "
    "(SELECT group_concat(id || ':' || hidden) FROM accounts)"
)


def engine_for(conn: Connection, as_of: str) -> Engine | None:
    key = str(conn.engine.url)
    stamp = (as_of, *conn.execute(text(_FINGERPRINT)).one())
    with _LOCK:
        hit = _CACHE.get(key)
        if hit is not None and hit[0] == stamp:
            return hit[1]
    eng = build(conn, as_of)
    with _LOCK:
        _CACHE[key] = (stamp, eng)
    return eng
