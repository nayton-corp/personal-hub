"""Mois budgétaire : il peut commencer un autre jour que le 1er (le jour de paie).

Un mois qui commence après le 15 porte le nom du mois civil où il finit : avec un début le 25,
« 2026-11 » va du 25 octobre au 24 novembre. Sinon, celui du mois où il commence : avec un
début le 5, « 2026-10 » va du 5 octobre au 4 novembre.

Le jour de début est un réglage daté (table `budget_period_rules`, audit M9) : une règle vaut
pour les mois budgétaires à partir de son `valid_from` (« AAAA-MM »), la plus récente règle
posée sur un même mois l'emporte, et les mois d'avant gardent leur découpage. Chaque connexion
relit les règles (FinanceDomain), pour que l'API, le planificateur et le CLI s'accordent.
"""

from __future__ import annotations

from datetime import date

MAX_DAY = 28  # tous les mois ont un 28
LATE = 15  # au-delà, le mois est nommé d'après sa fin
FOREVER = "1900-01"  # une règle sans date vaut depuis toujours
Rule = tuple[str, int]  # (premier mois budgétaire couvert « AAAA-MM », jour de début)
_state: dict[str, tuple[Rule, ...]] = {"rules": ()}


def rules() -> tuple[Rule, ...]:
    return _state["rules"]


def set_rules(found: list[Rule] | tuple[Rule, ...]) -> None:
    """Les règles lues en base, dans l'ordre où elles ont été posées : sur un même mois, la
    dernière l'emporte."""
    by_month: dict[str, int] = {}
    for valid_from, day in found:
        by_month[valid_from] = day if 1 <= day <= MAX_DAY else 1
    _state["rules"] = tuple(sorted(by_month.items()))


def set_start_day(day: int) -> None:
    """Un seul jour de début, depuis toujours (tests, bases d'avant les règles datées)."""
    set_rules([(FOREVER, day)])


def start_day(month: str | None = None) -> int:
    """Le jour de début du mois budgétaire `month` ; sans mois, celui de la dernière règle."""
    found = _state["rules"]
    if not found:
        return 1
    if month is None:
        return found[-1][1]
    day = 1
    for valid_from, d in found:
        if valid_from <= month:
            day = d
    return day


def _shift(y: int, m: int, delta: int) -> tuple[int, int]:
    i = y * 12 + (m - 1) + delta
    return i // 12, i % 12 + 1


def _start(month: str) -> date:
    """Le premier jour du mois budgétaire `month`, selon sa propre règle."""
    d = start_day(month)
    y, m = (int(x) for x in month.split("-"))
    first = (y, m) if d <= LATE else _shift(y, m, -1)
    return date(first[0], first[1], d)


def bounds(month: str) -> tuple[date, date]:
    """Premier jour du mois budgétaire `month` et premier jour du suivant : les mois se suivent
    sans trou ni chevauchement, même quand la règle change entre les deux (le mois de transition
    est plus court ou plus long)."""
    y, m = (int(x) for x in month.split("-"))
    ny, nm = _shift(y, m, 1)
    return _start(month), _start(f"{ny:04d}-{nm:02d}")


def month_of(day: date) -> str:
    """Le mois budgétaire qui contient `day` : le seul dont les bornes l'encadrent, parmi le mois
    civil et ses deux voisins (un mois budgétaire commence au plus tôt le 16 du mois civil d'avant
    et finit au plus tard le 15 du suivant)."""
    y, m = day.year, day.month
    for delta in (0, -1, 1):
        yy, mm = _shift(y, m, delta)
        candidate = f"{yy:04d}-{mm:02d}"
        first, nxt = bounds(candidate)
        if first <= day < nxt:
            return candidate
    return f"{y:04d}-{m:02d}"  # sans règle cohérente : le mois civil
