"""Mois budgétaire : il peut commencer un autre jour que le 1er (le jour de paie).

Un mois qui commence après le 15 porte le nom du mois civil où il finit : avec un début le 25,
« 2026-11 » va du 25 octobre au 24 novembre. Sinon, celui du mois où il commence : avec un
début le 5, « 2026-10 » va du 5 octobre au 4 novembre.

Le jour de début vit dans finance.db (table budget_period) et chaque connexion le relit
(FinanceDomain), pour que l'API, le planificateur et le CLI s'accordent.
"""

from __future__ import annotations

from datetime import date

MAX_DAY = 28  # tous les mois ont un 28
LATE = 15  # au-delà, le mois est nommé d'après sa fin
_state = {"day": 1}


def start_day() -> int:
    return _state["day"]


def set_start_day(day: int) -> None:
    _state["day"] = day if 1 <= day <= MAX_DAY else 1


def _shift(y: int, m: int, delta: int) -> tuple[int, int]:
    i = y * 12 + (m - 1) + delta
    return i // 12, i % 12 + 1


def bounds(month: str, day: int | None = None) -> tuple[date, date]:
    """Premier jour et lendemain du dernier jour du mois budgétaire `month`."""
    d = start_day() if day is None else day
    y, m = (int(x) for x in month.split("-"))
    first = (y, m) if d <= LATE else _shift(y, m, -1)
    nxt = _shift(*first, 1)
    return date(first[0], first[1], d), date(nxt[0], nxt[1], d)


def month_of(day: date, start: int | None = None) -> str:
    """Le mois budgétaire qui contient `day`."""
    d = start_day() if start is None else start
    y, m = day.year, day.month
    if day.day < d:
        y, m = _shift(y, m, -1)  # avant le début : période commencée le mois civil précédent
    if d > LATE:
        y, m = _shift(y, m, 1)  # période nommée d'après le mois où elle finit
    return f"{y:04d}-{m:02d}"
