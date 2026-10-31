"""Cours d'un instrument dans le temps (page d'un actif dans l'app) : les cours connus entre deux
dates, dans la devise de cotation, au plus un par jour et au plus 400 points."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Connection, text

MAX_POINTS = 400


def history(conn: Connection, isin: str, date_from: str | None, date_to: str) -> dict[str, Any]:
    """`{isin, name, currency, items: [{on_date, price}]}` ; un jour à plusieurs sources garde
    la dernière lue, comme la valorisation."""
    row = conn.execute(
        text("SELECT name, currency FROM instruments WHERE isin = :i"), {"i": isin}
    ).first()
    by_day: dict[str, tuple[str, str]] = {}
    for on, price, ccy in conn.execute(
        text(
            "SELECT on_date, price, currency FROM prices WHERE isin = :i "
            "AND (:f IS NULL OR on_date >= :f) AND on_date <= :t ORDER BY on_date, source"
        ),
        {"i": isin, "f": date_from, "t": date_to},
    ):
        by_day[on] = (price, ccy)
    days = sorted(by_day)
    if len(days) > MAX_POINTS:  # la fin toujours comprise
        stride = -(-len(days) // MAX_POINTS)
        days = days[::-1][::stride][::-1]
    ccys = {by_day[d][1] for d in days}
    return {
        "isin": isin,
        "name": row[0] if row else None,
        # une seule devise attendue ; sinon celle du dernier cours
        "currency": by_day[days[-1]][1] if days else (row[1] if row else None),
        "mixed_currencies": len(ccys) > 1,
        "items": [{"on_date": d, "price": by_day[d][0]} for d in days],
    }
