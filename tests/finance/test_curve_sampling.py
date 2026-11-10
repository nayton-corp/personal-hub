"""Points de la courbe : pas calés sur le calendrier, pas qui s'élargit au lieu d'un jour sur N,
plus haut et plus bas pris sur tous les jours (audit du 10/11, G1 et G2)."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from hub.domains.finance.patrimoine.model.returns import MAX_POINTS, Series, _sample, extremes


def calendar(start: str, n: int) -> list[str]:
    d0 = date.fromisoformat(start)
    return [(d0 + timedelta(days=k)).isoformat() for k in range(n)]


def series(values: list[int], ks: int = 0) -> Series:
    zeros = [0] * len(values)
    return Series(
        ks=ks,
        value=values,
        flow=zeros,
        income=zeros,
        fees=zeros,
        missing=[False] * len(values),
        index=[Decimal(1)] * len(values),
        positive=True,
    )


def test_weeks_fall_on_sundays_whatever_the_last_day() -> None:
    days = calendar("2026-01-01", 120)  # un jeudi
    for ke in (100, 101, 104):
        idx = _sample(days, 0, ke, "week")
        assert idx[0] == 0
        assert idx[-1] == ke
        inner = [days[k] for k in idx[1:-1]]
        assert all(date.fromisoformat(d).weekday() == 6 for d in inner)
    # le même dimanche est gardé quel que soit le jour où l'on regarde
    a = {days[k] for k in _sample(days, 0, 100, "week")[1:-1]}
    b = {days[k] for k in _sample(days, 0, 104, "week")[1:-1]}
    assert a <= b


def test_months_end_on_the_last_day_of_each_month() -> None:
    days = calendar("2025-11-10", 120)
    idx = _sample(days, 0, 119, "month")
    assert [days[k] for k in idx] == [
        "2025-11-10",
        "2025-11-30",
        "2025-12-31",
        "2026-01-31",
        "2026-02-28",
        "2026-03-09",
    ]


def test_a_long_period_widens_the_step_instead_of_skipping_days() -> None:
    days = calendar("2016-01-01", 3970)  # près de onze ans
    ke = len(days) - 1
    daily = _sample(days, 0, ke, "day")
    assert len(daily) <= MAX_POINTS
    # onze ans : ni le jour, ni la semaine ne tiennent, on passe aux fins de mois
    inner = daily[1:-1]
    assert all(days[k][5:7] != days[k + 1][5:7] for k in inner)
    short = _sample(days, ke - 300, ke, "day")
    assert short == list(range(ke - 300, ke + 1))
    two_years = _sample(days, ke - 730, ke, "day")
    assert all(date.fromisoformat(days[k]).weekday() == 6 for k in two_years[1:-1])


def test_extremes_come_from_every_day_not_from_the_kept_points() -> None:
    days = calendar("2026-01-01", 60)
    values = [1000 + k for k in range(60)]
    values[19] = 5000  # un mardi, entre deux dimanches
    values[23] = 10
    out = extremes(days, series(values), "CHF")
    assert out["high"]["on_date"] == days[19]
    assert out["high"]["value"]["minor"] == 5000
    assert out["low"]["on_date"] == days[23]
    kept = {days[k] for k in _sample(days, 0, 59, "week")}
    assert days[19] not in kept
    assert days[23] not in kept


def test_extremes_keep_the_first_day_on_a_tie_and_follow_the_window() -> None:
    days = calendar("2026-01-01", 30)
    out = extremes(days, series([500] * 10, ks=20), "CHF")
    assert out["high"]["on_date"] == days[20]
    assert out["low"]["on_date"] == days[20]
