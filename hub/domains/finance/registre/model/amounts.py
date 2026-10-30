"""Montants et mois des lectures : la forme des montants de l'API, les bornes d'un mois
budgétaire, et les noms des regroupements (« Autres », « à catégoriser »)."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal, localcontext
from typing import Any

from hub.domains.finance.registre.model import period
from hub.kernel.money import DECIMAL_CONTEXT, Money, base_currency, quantize

OTHERS = "autres"
MIN_COUNT_FOR_AGGREGATES = 3
UNCATEGORIZED = "a-categoriser"


def money(minor: int, currency: str) -> dict[str, int | str]:
    return Money(int(minor), currency).to_api()


def month_bounds(month: str) -> tuple[str, str]:
    """Premier jour et lendemain du dernier jour du mois budgétaire (period.py)."""
    start, end = period.bounds(month)
    return start.isoformat(), end.isoformat()


def shift_month(month: str, delta: int) -> str:
    y, m = (int(x) for x in month.split("-"))
    index = y * 12 + (m - 1) + delta
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def in_base(minor: int) -> dict[str, Any]:
    """Montant de l'API dans la devise de base de l'instance."""
    return money(minor, base_currency())


class FutureMonth(ValueError):
    pass


def month_end(month: str) -> date:
    _, end = month_bounds(month)
    return date.fromisoformat(end) - timedelta(days=1)


def as_of(month: str, today: date) -> date:
    """Fin du mois, ou aujourd'hui pour le mois en cours ; un mois futur est refusé."""
    start, _ = month_bounds(month)
    if date.fromisoformat(start) > today:
        raise FutureMonth(month)
    return min(month_end(month), today)


def previous_months(month: str, n: int) -> list[str]:
    """Les `n` mois complets avant `month`, du plus ancien au plus récent."""
    return [shift_month(month, -k) for k in range(n, 0, -1)]


def period_months(month: str, period: str) -> list[str]:
    """`m` : le mois lui-même ; `q` : les trois mois complets qui le précèdent."""
    return [month] if period == "m" else previous_months(month, 3)


def span(months: list[str]) -> tuple[str, str]:
    return month_bounds(months[0])[0], month_bounds(months[-1])[1]


def ratio(num: int, den: int, places: int = 4) -> str | None:
    if den == 0:
        return None
    with localcontext(DECIMAL_CONTEXT):
        return str(quantize(Decimal(num) / Decimal(den), places))


def days_left(month: str, today: date) -> int:
    """Jours après aujourd'hui jusqu'à la fin du mois ; 0 pour un mois passé."""
    return max(0, (month_end(month) - today).days)


def year_months(month: str) -> list[str]:
    """Mois budgétaires de l'année de `month`, de janvier à `month` compris."""
    return [f"{month[:4]}-{m:02d}" for m in range(1, int(month[5:7]) + 1)]
