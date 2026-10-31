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

from collections.abc import Iterable, Sequence
from decimal import Decimal, localcontext
from typing import Any

from hub.domains.finance.patrimoine.app.perf_events import events
from hub.domains.finance.patrimoine.app.perf_lines import ABSENT, Engine, Line
from hub.domains.finance.patrimoine.model.returns import (
    ONE,
    RATE_CONTEXT,
    Series,
    _period_json,
    _periods,
    _rate,
    _risk,
    _sample,
    _span,
    mwr,
)
from hub.domains.finance.registre.model.amounts import money

STEPS = ("day", "week", "month")
MIN_BASE = 100  # un franc : en dessous, pas de rendement du jour


# --- construction ------------------------------------------------------------------------------


# --- mémoire -----------------------------------------------------------------------------------


# --- lecture d'une sélection -------------------------------------------------------------------


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
        "events": events(eng, chosen, ks, ke, s.value),
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
        "events": [],
    }
