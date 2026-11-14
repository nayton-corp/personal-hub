"""Achats réguliers : repérer, dans des achats datés, une série qui ressemble à une décision prise
à l'avance (un DCA : « le 1er du mois, j'achète pour 200 CHF de bitcoin »). Pur : des dates et
des montants en entrée, une série ou rien en sortie.

Le hub préfère rater une série que d'en inventer une. Une série n'est retenue que si tout est
vrai à la fois (`problems` dit ce qui manque) :

- assez d'achats d'affilée (`MIN_COUNT` : quatre chaque mois, six chaque semaine) ;
- un rythme régulier : chaque écart entre deux achats tombe dans la plage du rythme ;
- des montants proches : chacun à `SPREAD_PCT` % au plus de la médiane ;
- une série encore en cours : le dernier achat date de moins d'un écart maximal ;
- aucune vente pendant la série.

Un achat en plus entre deux échéances (un coup de cœur) ne casse pas la série : il n'en fait
simplement pas partie. Mais s'il y a plus d'achats hors série que la moitié de la série, ce
n'est pas une décision régulière (des achats fréquents dont on aurait extrait un mois sur quatre) :
rien n'est retenu. Plusieurs achats le même jour comptent pour un.
"""

from __future__ import annotations

import statistics
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date

# rythme : (écart minimal, écart maximal) en jours ; chaque semaine d'abord (voir `detect`)
CADENCES: dict[str, tuple[int, int]] = {"weekly": (6, 8), "monthly": (26, 35)}
MIN_COUNT = {"monthly": 4, "weekly": 6}
SPREAD_PCT = 15
MAX_SERIES = 24  # on regarde au plus deux ans d'échéances mensuelles


@dataclass(frozen=True)
class Buy:
    on: date
    amount: int  # centimes de la devise de base, positif


@dataclass(frozen=True)
class Series:
    cadence: str  # monthly | weekly
    day: int  # jour du mois (1 à 28) ou de la semaine (0 : lundi)
    amount: int  # montant arrondi, centimes
    buys: tuple[Buy, ...]  # la série, du plus ancien au plus récent

    @property
    def first(self) -> date:
        return self.buys[0].on

    @property
    def last(self) -> date:
        return self.buys[-1].on

    @property
    def low(self) -> int:
        return min(b.amount for b in self.buys)

    @property
    def high(self) -> int:
        return max(b.amount for b in self.buys)


def by_day(buys: Iterable[Buy]) -> list[Buy]:
    """Un achat par jour (la somme), du plus ancien au plus récent."""
    days: dict[date, int] = {}
    for b in buys:
        if b.amount > 0:
            days[b.on] = days.get(b.on, 0) + b.amount
    return [Buy(d, a) for d, a in sorted(days.items())]


def _chain(buys: Sequence[Buy], cadence: str) -> list[Buy]:
    """La plus longue suite d'achats au rythme qui finit au dernier achat, en remontant : avant
    chaque achat, celui dans la plage du rythme dont le montant est le plus proche."""
    lo, hi = CADENCES[cadence]
    chain = [buys[-1]]
    i = len(buys) - 1
    while len(chain) < MAX_SERIES:
        cur = chain[-1]
        fits = [
            (abs(b.amount - cur.amount), -j, j)
            for j, b in enumerate(buys[:i])
            if lo <= (cur.on - b.on).days <= hi
        ]
        if not fits:
            break
        _gap, _neg, i = min(fits)
        chain.append(buys[i])
    return chain[::-1]


def _close(amounts: Sequence[int]) -> bool:
    mid = statistics.median(amounts)
    return all(abs(a - mid) * 100 <= mid * SPREAD_PCT for a in amounts)


def _trim(chain: list[Buy]) -> list[Buy]:
    """Les achats les plus récents dont les montants restent proches : un ancien montant différent
    (avant une augmentation) sort de la série au lieu de la refuser."""
    for start in range(len(chain)):
        if _close([b.amount for b in chain[start:]]):
            return chain[start:]
    return []  # pragma: no cover - un seul achat est toujours proche de lui-même


def round_amount(minor: int) -> int:
    """Un montant rond : au franc près sous 100, à 10 francs près au-delà."""
    step = 100 if minor < 10_000 else 1_000
    return max(step, (minor + step // 2) // step * step)


def _day(cadence: str, buys: Sequence[Buy]) -> int:
    """Le jour le plus fréquent (le plus tôt à égalité) ; au plus le 28 pour un mois."""
    days = [b.on.weekday() if cadence == "weekly" else min(b.on.day, 28) for b in buys]
    count = Counter(days)
    best = max(count.values())
    return min(d for d, n in count.items() if n == best)


def problems(
    series: Series, sold: Iterable[date], today: date, others: Sequence[Buy] = ()
) -> list[str]:
    """Pourquoi cette série n'est pas une stratégie (vide : elle en est une). `others` : tous
    les achats de l'actif, pour compter ceux faits hors série pendant la série."""
    out = []
    inside = {b.on for b in series.buys}
    extra = sum(1 for b in others if series.first <= b.on <= series.last and b.on not in inside)
    if extra * 2 > len(series.buys):
        out.append("trop d'autres achats pendant la série")
    if len(series.buys) < MIN_COUNT[series.cadence]:
        out.append("trop peu d'achats")
    if not _close([b.amount for b in series.buys]):
        out.append("montants trop différents")
    if (today - series.last).days > CADENCES[series.cadence][1]:
        out.append("série arrêtée")
    if any(series.first <= d <= today for d in sold):
        out.append("vente pendant la série")
    return out


def detect(buys: Iterable[Buy], sold: Iterable[date], today: date) -> Series | None:
    """La série d'achats réguliers en cours, ou None. Chaque semaine avant chaque mois : des
    achats mensuels n'ont jamais l'air hebdomadaires, alors que quatre semaines d'achats
    hebdomadaires ressemblent à un mois."""
    days = [b for b in by_day(buys) if b.on <= today]
    sales = list(sold)
    if not days:
        return None
    for cadence in CADENCES:
        chain = _trim(_chain(days, cadence))
        s = Series(
            cadence,
            _day(cadence, chain),
            round_amount(int(statistics.median(b.amount for b in chain))),
            tuple(chain),
        )
        if not problems(s, sales, today, days):
            return s
    return None


def amount_band(minor: int) -> int:
    """Une tranche de montant (≈ 30 % de large) : refusée une fois, une série ne revient que si
    son montant change de tranche."""
    band, edge = 0, 1_000
    while edge <= minor:
        edge = edge * 13 // 10
        band += 1
    return band
