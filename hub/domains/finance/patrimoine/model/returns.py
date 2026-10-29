"""Rendements, sans base : rendement personnel annualisé (TRI, par bissection), points d'une
courbe, périodes (mois, années) et risque (volatilité, pire baisse), en décimales exactes."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Context, Decimal, localcontext
from typing import Any

from hub.domains.finance.registre.model.amounts import money
from hub.kernel.money import DECIMAL_CONTEXT

MAX_POINTS = 400
MWR_MIN_DAYS = 365
VOL_MIN_WEEKS = 8
ONE = Decimal(1)
RATE_CONTEXT = Context(prec=18)  # rendements : 18 chiffres suffisent, et vont plus vite
RATE_EPS = Decimal("1e-9")
RATE_STEP = Decimal("0.000001")


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


def _period_json(p: dict[str, Any], ccy: str) -> dict[str, Any]:
    return {
        "period": p["period"],
        "net_flows": money(p["net_flows"], ccy),
        "gain": money(p["gain"], ccy),
        "twr": _rate(p["twr"]),
    }
