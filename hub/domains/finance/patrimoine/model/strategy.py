"""Stratégies : les règles, pures. Chaque fonction prend des réglages (seuils, montants, dates)
et des chiffres à une date, et dit si une étape est atteinte : le même calcul sert à la
vérification de nuit et à un rejeu sur le passé. Aucune ne cherche un « meilleur » réglage.

Trois genres :
- `ladder` : vendre par paliers, quand la valeur atteint un pourcentage du prix d'achat ;
- `recurring` : acheter à date fixe (chaque mois, chaque semaine) ;
- `dip` : acheter quand le cours a beaucoup baissé depuis son plus haut récent.

Garde-fous du produit, tenus ici : quatre paliers au plus, dix points entre deux paliers, une
baisse d'au moins 15 %, une étape à la fois.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from itertools import pairwise

KINDS = ("ladder", "recurring", "dip")
GROUP_ALT = "crypto:alt"  # toute la crypto sauf le bitcoin et les stablecoins
GROUP_ALL = "crypto:all"  # toute la crypto sauf les stablecoins
GROUPS = {GROUP_ALT: "Altcoins", GROUP_ALL: "Crypto"}
BITCOIN = "CRYPTO:BTC"

MAX_TIERS = 4
MIN_TIER_GAP = 10  # points de pourcentage entre deux paliers
MIN_DROP_PCT = 15
WINDOWS = (90, 365)  # jours : « plus haut des 3 derniers mois », « des 12 derniers mois »
DONE_SHARE_PCT = 80  # une étape se coche quand le journal montre 80 % de ce qui était prévu
REMIND_AFTER_DAYS = 3  # achat régulier pas encore vu : un seul rappel
EARLY_DAYS = 3  # un achat fait jusqu'à trois jours avant l'échéance compte pour elle


@dataclass(frozen=True, order=True)
class Tier:
    at_pct: int  # niveau, en % du prix d'achat (100 : sans perte)
    sell_pct: int  # part de ce qui est tenu ce jour-là, à vendre


def tiers_problem(tiers: Sequence[Tier]) -> str | None:
    """Pourquoi ces paliers ne sont pas acceptables, ou None."""
    if not 1 <= len(tiers) <= MAX_TIERS:
        return f"entre 1 et {MAX_TIERS} paliers"
    ordered = sorted(tiers)
    if any(b.at_pct - a.at_pct < MIN_TIER_GAP for a, b in pairwise(ordered)):
        return f"au moins {MIN_TIER_GAP} points entre deux paliers"
    return None


def ratio_pct(value: int, cost: int) -> Decimal | None:
    """La valeur en pourcentage du prix d'achat ; None sans prix d'achat."""
    return None if cost <= 0 else Decimal(value) * 100 / Decimal(cost)


def ladder_next(
    tiers: Iterable[Tier], closed: frozenset[int], ratio: Decimal | None
) -> Tier | None:
    """Le premier palier pas encore clos, s'il est atteint : une étape à la fois, dans l'ordre,
    même si le niveau a sauté deux paliers d'un coup."""
    for t in sorted(tiers):
        if t.at_pct in closed:
            continue
        return t if ratio is not None and ratio >= t.at_pct else None
    return None


def planned_sale(value: int, sell_pct: int) -> int:
    return value * sell_pct // 100


def recurring_due(cadence: str, day: int, today: date) -> date:
    """La dernière échéance au plus tard aujourd'hui. `day` : jour du mois (1 à 28), ou jour de
    la semaine (0 : lundi)."""
    if cadence == "weekly":
        return today - timedelta(days=(today.weekday() - day) % 7)
    if today.day >= day:
        return today.replace(day=day)
    last = today.replace(day=1) - timedelta(days=1)
    return last.replace(day=day)


def recurring_next(cadence: str, day: int, today: date) -> date:
    """La prochaine échéance après aujourd'hui."""
    due = recurring_due(cadence, day, today)
    if cadence == "weekly":
        return due + timedelta(days=7)
    first = (due.replace(day=28) + timedelta(days=4)).replace(day=1)
    return first.replace(day=day)


def recurring_key(cadence: str, due: date) -> str:
    return due.isoformat() if cadence == "weekly" else due.isoformat()[:7]


@dataclass(frozen=True)
class Dip:
    peak_on: str
    peak: Decimal
    last_on: str
    last: Decimal
    drop_pct: Decimal  # baisse depuis le plus haut, positive


def dip(prices: Sequence[tuple[str, Decimal]], window_days: int, today: date) -> Dip | None:
    """Le plus haut de la fenêtre et la baisse depuis ; None sans cours dans la fenêtre. Deux
    plus hauts égaux : le plus récent, pour qu'un sommet retouché compte comme un nouveau."""
    since = (today - timedelta(days=window_days)).isoformat()
    seen = [(d, p) for d, p in prices if since <= d <= today.isoformat() and p > 0]
    if not seen:
        return None
    seen.sort()
    peak_on, peak = max(seen, key=lambda x: (x[1], x[0]))
    last_on, last = seen[-1]
    return Dip(peak_on, peak, last_on, last, (peak - last) * 100 / peak)


def dip_reached(d: Dip | None, drop_pct: int, last_opened_on: str | None) -> bool:
    """Une seule alerte par baisse : il faut un nouveau plus haut, formé après la dernière
    alerte, pour qu'elle revienne."""
    if d is None or d.drop_pct < drop_pct:
        return False
    return last_opened_on is None or d.peak_on > last_opened_on


def settled(done: int, planned: int | None) -> bool:
    """Le journal montre-t-il à peu près ce qui était prévu ?"""
    return planned is not None and planned > 0 and done * 100 >= planned * DONE_SHARE_PCT
