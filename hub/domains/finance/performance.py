"""Performance du patrimoine : gain, apports nets, rendement pondéré dans le temps, rendement
personnel (TRI), pour toute sélection de lignes.

Une *ligne* est un instrument d'un compte à positions, le solde d'un compte, ou une dette.
Chaque jour depuis la première écriture, elle a une valeur dans la devise de base (comme
valuation.py) et un *flux* : l'argent qui y entre ou en sort. Le reste de la variation est
l'effet marché.

- Solde d'un compte : le flux, ce sont les écritures du jour converties au cours du jour, sauf
  les revenus (catégories « rendement », « intérêts et dividendes ») et les frais (« frais de
  placement »), qui sont de l'effet marché comme la variation du change. Un virement entre deux
  de mes comptes est un flux pour chacun.
- Instrument : le flux, ce sont les parts achetées ou vendues, au cours du jour.
- Dette (valeur négative) : le flux, ce sont les paiements ; l'effet marché, les intérêts.
- Une ligne qui devient valorisable (premier cours, dette ouverte) ou cesse de l'être entre ou
  sort par un flux, jamais par un effet marché. Une ligne qui devrait avoir une valeur mais n'a
  pas de cours (ou pas de change) est signalée : la période est alors « incomplète ».

Pour une sélection, les flux internes s'annulent (virement BCF → VIAC sur le total, achat de
parts payé par les liquidités du courtier) : le patrimoine total n'a pour flux que ce qui entre
de l'extérieur ou en sort (salaire, dépenses).

Rendement pondéré dans le temps : produit des rendements journaliers (V(t) − F(t)) / V(t − 1),
le flux étant placé en fin de journée ; un jour sans base positive est sauté. Rendement personnel :
taux annuel qui égalise valeur de départ, flux datés et valeur de fin, donné à partir d'un an.

Le calcul complet est gardé en mémoire tant que le registre, les cours, le change et les dettes
n'ont pas changé (empreinte relue à chaque demande). Seuls des agrégats en sortent.
"""

from __future__ import annotations

import threading
from array import array
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Context, Decimal, localcontext
from typing import Any

from sqlalchemy import Connection, text

from hub.domains.finance import debts, institutions, valuation
from hub.domains.finance.reads import money
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
STEPS = ("day", "week", "month")
MAX_POINTS = 400
MIN_BASE = 100  # un franc : en dessous, pas de rendement du jour
MWR_MIN_DAYS = 365
VOL_MIN_WEEKS = 8
ONE = Decimal(1)
RATE_CONTEXT = Context(prec=18)  # rendements : 18 chiffres suffisent, et vont plus vite
RATE_EPS = Decimal("1e-9")
RATE_STEP = Decimal("0.000001")


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


# --- construction ------------------------------------------------------------------------------


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
    return Engine(days, {i: ln for i, ln in lines.items() if _used(ln)}, ccy)


def _used(ln: Line) -> bool:
    return any(v != ABSENT for v in ln.value) or any(ln.missing) or any(ln.income) or any(ln.fees)


# --- mémoire -----------------------------------------------------------------------------------

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


# --- lecture d'une sélection -------------------------------------------------------------------


@dataclass
class Series:
    ks: int
    value: list[int]
    flow: list[int]  # flow[0] = 0 : le départ n'est pas un flux
    income: list[int]
    fees: list[int]
    missing: list[bool]
    index: list[Decimal]  # indice du rendement pondéré, 1 au départ
    positive: bool  # au moins un jour avec une base positive


def _series(lines: Sequence[Line], ks: int, ke: int) -> Series:
    m = ke - ks + 1
    value, flow, inc, fee = [0] * m, [0] * m, [0] * m, [0] * m
    missing = [False] * m
    for ln in lines:
        lv, lf, li, le, lm = ln.value, ln.flow, ln.income, ln.fees, ln.missing
        for j in range(m):
            k = ks + j
            v = lv[k]
            if v != ABSENT:
                value[j] += v
            if j:
                flow[j] += lf[k]
                inc[j] += li[k]
                fee[j] += le[k]
            if lm[k]:
                missing[j] = True
    # une ligne déjà là au départ n'entre pas par un flux : flow[0] reste 0
    index = [ONE] * m
    positive = False
    x = ONE
    with localcontext(RATE_CONTEXT):
        for j in range(1, m):
            if value[j - 1] >= MIN_BASE:
                positive = True
                x = x * (value[j] - flow[j]) / value[j - 1]
            index[j] = x
    return Series(ks, value, flow, inc, fee, missing, index, positive)


def _span(a: str, b: str) -> int:
    return (date.fromisoformat(b) - date.fromisoformat(a)).days


def mwr(days: Sequence[str], s: Series) -> Decimal | None:
    """Rendement personnel annuel (TRI), à partir d'un an de recul ; None sinon. Les flux sont
    groupés par semaine (à la fin de la semaine), ce qui ne change le taux qu'à la marge."""
    start, end = days[s.ks], days[s.ks + len(s.value) - 1]
    total = _span(start, end)
    if total < MWR_MIN_DAYS:
        return None
    weeks: dict[int, int] = {}
    for j, f in enumerate(s.flow):
        if j and f:
            w = min(total, (j // 7 + 1) * 7)
            weeks[w] = weeks.get(w, 0) - f
    with localcontext(RATE_CONTEXT):
        cash = [(Decimal(0), Decimal(-s.value[0]))]
        cash += [(Decimal(d) / 365, Decimal(c)) for d, c in sorted(weeks.items()) if c]
        cash.append((Decimal(total) / 365, Decimal(s.value[-1])))

        def npv(r: Decimal) -> Decimal:
            ln = (ONE + r).ln()
            return sum((c * (-t * ln).exp() for t, c in cash), Decimal(0))

        lo, hi = Decimal("-0.99"), Decimal(10)
        f_lo, f_hi = npv(lo), npv(hi)
        if f_lo * f_hi > 0:
            return None
        for _ in range(60):
            mid = (lo + hi) / 2
            f_mid = npv(mid)
            if f_lo * f_mid <= 0:
                hi = mid
            else:
                lo, f_lo = mid, f_mid
            if hi - lo < RATE_EPS:
                break
        return (lo + hi) / 2


def _rate(x: Decimal | None) -> str | None:
    if x is None or not x.is_finite():
        return None
    return str(x.quantize(RATE_STEP, context=DECIMAL_CONTEXT))


def _summary(days: Sequence[str], s: Series, ccy: str, *, with_mwr: bool = True) -> dict[str, Any]:
    flows = sum(s.flow)
    gain = s.value[-1] - s.value[0] - flows
    income, fees = sum(s.income), sum(s.fees)
    twr = s.index[-1] - 1 if s.positive else None
    span = _span(days[s.ks], days[s.ks + len(s.value) - 1])
    yearly = None
    if twr is not None and span >= 365 and twr > -1:
        with localcontext(RATE_CONTEXT):
            yearly = (1 + twr) ** (Decimal(365) / span) - 1
    return {
        "start": money(s.value[0], ccy),
        "end": money(s.value[-1], ccy),
        "net_flows": money(flows, ccy),
        "gain": money(gain, ccy),
        "income": money(income, ccy),
        "fees": money(fees, ccy),
        # plus-values et change : le reste du gain
        "price_effect": money(gain - income - fees, ccy),
        "twr": _rate(twr),
        "twr_yearly": _rate(yearly),
        "mwr": _rate(mwr(days, s)) if with_mwr else None,
        "complete": not any(s.missing),
    }


def _sample(days: Sequence[str], ks: int, ke: int, step: str) -> list[int]:
    """Indices des points de la courbe : le départ, chaque pas, la fin."""
    if step == "day":
        idx = list(range(ks, ke + 1))
    elif step == "week":
        idx = list(range(ke, ks - 1, -7))[::-1]
    else:
        idx = [k for k in range(ks, ke) if days[k][5:7] != days[k + 1][5:7]] + [ke]
    if idx[0] != ks:
        idx.insert(0, ks)
    if len(idx) > MAX_POINTS:  # au plus MAX_POINTS, la fin toujours comprise
        stride = -(-len(idx) // MAX_POINTS)
        idx = idx[::-1][::stride][::-1]
        if idx[0] != ks:
            idx.insert(0, ks)
    return idx


def _periods(days: Sequence[str], s: Series, width: int) -> list[dict[str, Any]]:
    """Par mois (width=7, 'AAAA-MM') ou par année (width=4) : flux, gain, rendement."""
    out: list[dict[str, Any]] = []
    m = len(s.value)
    start = 0
    for j in range(1, m):
        k = s.ks + j
        if j == m - 1 or days[k][:width] != days[k + 1][:width]:
            flows = sum(s.flow[start + 1 : j + 1])
            out.append(
                {
                    "period": days[k][:width],
                    "net_flows": flows,
                    "gain": s.value[j] - s.value[start] - flows,
                    "twr": s.index[j] / s.index[start] - 1 if s.positive else None,
                }
            )
            start = j
    return out


def _risk(days: Sequence[str], s: Series) -> dict[str, Any] | None:
    if not s.positive:
        return None
    peak, peak_j = s.index[0], 0
    worst, at, from_ = Decimal(0), 0, 0
    for j, x in enumerate(s.index):
        if x > peak:
            peak, peak_j = x, j
        dd = x / peak - 1
        if dd < worst:
            worst, at, from_ = dd, j, peak_j
    recovered = None
    if worst < 0:
        top = s.index[from_]
        recovered = next(
            (days[s.ks + j] for j in range(at, len(s.index)) if s.index[j] >= top), None
        )
    vol = None
    with localcontext(RATE_CONTEXT):
        weekly = [s.index[j] / s.index[j - 7] - 1 for j in range(len(s.index) - 1, 6, -7)]
        if len(weekly) >= VOL_MIN_WEEKS:
            mean = sum(weekly, Decimal(0)) / len(weekly)
            var = sum(((w - mean) ** 2 for w in weekly), Decimal(0)) / (len(weekly) - 1)
            vol = (var * 52).sqrt()
    return {
        "max_drawdown": _rate(worst),
        "peak_on": days[s.ks + from_] if worst < 0 else None,
        "trough_on": days[s.ks + at] if worst < 0 else None,
        "recovered_on": recovered,
        "volatility": _rate(vol),
    }


def _group(
    days: Sequence[str], lines: Iterable[Line], key: str, ks: int, ke: int, ccy: str
) -> dict[str, Any]:
    groups: dict[str, list[Line]] = {}
    for ln in lines:
        groups.setdefault(getattr(ln, key), []).append(ln)
    return {
        k: _summary(days, _series(ls, ks, ke), ccy, with_mwr=False)
        for k, ls in sorted(groups.items())
    }


def report(
    eng: Engine,
    ids: Sequence[str] | None,
    date_from: str | None,
    date_to: str | None,
    step: str,
) -> dict[str, Any]:
    """La sélection `ids` (lignes de l'app par défaut) entre deux dates : courbe, résumé, par
    compte et par actif, par mois et par année, risque."""
    known = eng.lines
    chosen = [known[i] for i in (ids if ids else eng.default_ids()) if i in known]
    ks = eng.index(date_from or eng.days[0])
    ke = eng.index(date_to or eng.days[-1])
    if ke < ks:
        ks = ke
    s = _series(chosen, ks, ke)
    days, ccy = eng.days, eng.currency
    peaks: list[Decimal] = []
    top = Decimal(0)
    for x in s.index:
        top = max(top, x)
        peaks.append(top)
    cum, run = [], 0
    for f in s.flow:
        run += f
        cum.append(run)
    points = []
    for k in _sample(days, ks, ke, step):
        j = k - ks
        flows = cum[j]
        points.append(
            {
                "on_date": days[k],
                "value": money(s.value[j], ccy),
                "net_flows": money(flows, ccy),
                "gain": money(s.value[j] - s.value[0] - flows, ccy),
                "twr": _rate(s.index[j] - 1) if s.positive else None,
                "drawdown": _rate(s.index[j] / peaks[j] - 1) if s.positive else None,
                "complete": not s.missing[j],
            }
        )
    risk = _risk(days, s)
    return {
        "currency": ccy,
        "from": days[ks],
        "to": days[ke],
        "first_day": days[0],
        "lines": len(chosen),
        "summary": _summary(days, s, ccy),
        "items": points,
        "by_account": _group(days, chosen, "account_id", ks, ke, ccy),
        "by_asset": _group(days, chosen, "asset", ks, ke, ccy),
        "by_line": {
            ln.id: _summary(days, _series([ln], ks, ke), ccy, with_mwr=False) for ln in chosen
        },
        "by_month": [_period_json(p, ccy) for p in _periods(days, s, 7)],
        "by_year": [_period_json(p, ccy) for p in _periods(days, s, 4)],
        "risk": risk,
        "missing": sorted({ln.id for ln in chosen if any(ln.missing[ks : ke + 1])}),
    }


def _period_json(p: dict[str, Any], ccy: str) -> dict[str, Any]:
    return {
        "period": p["period"],
        "net_flows": money(p["net_flows"], ccy),
        "gain": money(p["gain"], ccy),
        "twr": _rate(p["twr"]),
    }


def empty(ccy: str) -> dict[str, Any]:
    """Sans aucune écriture : la même forme, vide."""
    return {
        "currency": ccy,
        "from": None,
        "to": None,
        "first_day": None,
        "lines": 0,
        "summary": None,
        "items": [],
        "by_account": {},
        "by_asset": {},
        "by_line": {},
        "by_month": [],
        "by_year": [],
        "risk": None,
        "missing": [],
    }
