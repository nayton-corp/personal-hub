"""Limite de débit par fenêtre d'une minute, tenue dans `core.db` (aucun état en mémoire)."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import Connection, Engine, text

from hub.core.errors import Problem
from hub.kernel.clock import iso, utcnow


def hit(conn: Connection, key: str) -> int:
    window = iso(utcnow().replace(second=0, microsecond=0))
    conn.execute(
        text(
            "INSERT INTO rate_limits (actor, window_start, count) VALUES (:k, :w, 1) "
            "ON CONFLICT (actor, window_start) DO UPDATE SET count = count + 1"
        ),
        {"k": key, "w": window},
    )
    count: int = conn.execute(
        text("SELECT count FROM rate_limits WHERE actor = :k AND window_start = :w"),
        {"k": key, "w": window},
    ).scalar_one()
    return count


def enforce(engine: Engine, key: str, limit: int) -> None:
    # transaction à part : le compteur reste compté même si la requête échoue ensuite
    with engine.begin() as conn:
        count = hit(conn, key)
    if count > limit:
        raise Problem("rate_limited", headers={"Retry-After": "60"})


def purge(conn: Connection) -> int:
    cutoff = iso(utcnow() - timedelta(hours=1))
    return conn.execute(
        text("DELETE FROM rate_limits WHERE window_start < :c"), {"c": cutoff}
    ).rowcount
