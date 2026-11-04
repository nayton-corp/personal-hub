"""Rythme du mois budgétaire, projection à sa fin et états (audit M3) : une seule règle, lue
par le budget de l'app, l'outil de l'assistant et les sentinelles de nuit ; le front affiche.

- Le rythme est la part du mois écoulée, aujourd'hui compris.
- Une dépense variable se projette au prorata du mois dès le 7e jour (avant, trop tôt : elle
  vaut ce qu'elle est) ; une dépense fixe finit au plus haut de ce qu'elle a coûté et de sa
  cible (le loyer restant tombera).
- Une cible est « dépassée » quand le dépensé la passe, « probablement dépassée » quand la
  projection la passe de plus de 10 % ; une fixe atteinte est « payée ».
- Un mois clos n'a ni rythme ni projection : il est « clos », avec ou sans avance.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

MIN_DAY_FOR_PROJECTION = 7  # jour du mois à partir duquel le rythme dit quelque chose
LIKELY_MARGIN_PCT = 10  # projection au-delà de la cible de plus de 10 % : dépassement probable
EXPENSE_GROUPS = ("fixed", "variable")


@dataclass(frozen=True)
class Clock:
    """Où en est la période : jours écoulés (aujourd'hui compris), longueur, et si elle est en
    cours (la seule où un rythme et une projection ont un sens)."""

    elapsed: int
    length: int
    current: bool

    @property
    def fraction(self) -> tuple[int, int] | None:
        """(écoulé, longueur) de la période en cours, None sinon."""
        return (self.elapsed, self.length) if self.current else None


def clock(start: date, after: date, today: date) -> Clock:
    """La période `[start, after)` vue d'aujourd'hui."""
    length = max(1, (after - start).days)
    if today < start:
        return Clock(0, length, False)
    if today >= after:
        return Clock(length, length, False)
    return Clock((today - start).days + 1, length, True)


def projected(spent: int, group: str, target: int | None, c: Clock) -> int:
    """Ce que la catégorie aura coûté à la fin de la période (`spent` en positif)."""
    value = max(0, spent)
    if not c.current:
        return value
    if group == "fixed":
        return max(value, target or 0)
    if c.elapsed >= MIN_DAY_FOR_PROJECTION:
        return value * c.length // c.elapsed
    return value


def line_state(spent: int, group: str, target: int | None, c: Clock) -> str:
    """`untracked` (sans cible), `over`, `likely_over`, `paid` (fixe atteinte) ou `ok`."""
    if target is None:
        return "untracked"
    value = max(0, spent)
    if value > target:
        return "over"
    if group == "fixed":
        return "paid" if value >= target else "ok"
    if c.current and projected(value, group, target, c) * 100 > target * (100 + LIKELY_MARGIN_PCT):
        return "likely_over"
    return "ok"


def period_state(budget: int | None, rest: int | None, projection: int | None, c: Clock) -> str:
    """`no_budget`, `closed_ok`, `closed_over`, `over`, `likely_over` ou `on_pace`."""
    if budget is None or rest is None:
        return "no_budget"
    if not c.current:
        return "closed_over" if rest < 0 else "closed_ok"
    if rest < 0:
        return "over"
    if projection is not None and projection * 100 > budget * (100 + LIKELY_MARGIN_PCT):
        return "likely_over"
    return "on_pace"


def expected_share(fixed: int, variable: int, c: Clock) -> tuple[int, int] | None:
    """Part du budget qui devrait être dépensée à ce jour : les fixes en entier, les variables
    au rythme ; (numérateur, dénominateur) en centimes, None hors période en cours."""
    if not c.current or fixed + variable <= 0:
        return None
    return fixed * c.length + variable * c.elapsed, (fixed + variable) * c.length
