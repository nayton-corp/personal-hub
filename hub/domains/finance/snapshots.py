"""Instantanés du patrimoine (ticket L2-01).

Un instantané par fin de mois depuis la première écriture, plus un à la date du calcul. La
série est toujours recalculée en entier, dans une seule transaction : un relevé ancien arrivé
après coup (reprise d'historique) corrige donc aussi les mois passés. Le recalcul part de la
tâche de nuit et des événements `import.applied` et `debt.changed` (une dette créée, modifiée
ou un solde constaté), lus par curseur dans la boîte de sortie.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from sqlalchemy import Connection, Engine, text

from hub.core import canonical
from hub.core.clock import now_iso
from hub.core.db import begin_immediate
from hub.core.logging import get_logger
from hub.core.money import base_currency
from hub.domains.finance import valuation
from hub.domains.finance.reads import money

log = get_logger("hub.finance.snapshots")
TRIGGER = "import.applied"
TRIGGERS = (TRIGGER, "debt.changed")


def month_ends(first: date, as_of: date) -> list[date]:
    """Fins de mois de `first` jusqu'à la veille de `as_of`, puis `as_of`."""
    out = []
    y, m = first.year, first.month
    while True:
        end = date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)
        if end >= as_of:
            break
        out.append(end)
        y, m = y + (m == 12), m % 12 + 1
    out.append(as_of)
    return out


def snapshot_dates(conn: Connection, as_of: date) -> list[str]:
    first = conn.execute(
        text("SELECT min(booking_date) FROM entries WHERE booking_date <= :d"),
        {"d": as_of.isoformat()},
    ).scalar_one()
    if first is None:
        return []
    return [d.isoformat() for d in month_ends(date.fromisoformat(first), as_of)]


def compute(conn: Connection, as_of: date) -> list[dict[str, Any]]:
    """La série telle qu'elle doit être stockée (sans l'horodatage du calcul)."""
    return [
        {
            "on_date": v.on_date,
            "net_worth_minor": v.net_worth,
            "deposits_cum_minor": v.deposits,
            "by_envelope_json": canonical.dumps(v.by_envelope),
            "by_account_json": canonical.dumps(v.by_account),
        }
        for v in valuation.series(conn, snapshot_dates(conn, as_of))
    ]


@dataclass(frozen=True)
class Refresh:
    recomputed: bool
    rows: int
    reason: str


def _state(conn: Connection) -> tuple[int, int, str] | None:
    row = conn.execute(
        text("SELECT event_cursor, entries_seq, as_of FROM snapshot_state WHERE id = 1")
    ).first()
    return (int(row[0]), int(row[1]), str(row[2])) if row else None


def refresh(engine: Engine, as_of: date, *, force: bool = False) -> Refresh:
    """Recalcule si un import a été appliqué depuis le dernier calcul, si le registre a
    grandi (ouverture d'un compte), si la date a changé, ou sur demande (tâche de nuit)."""
    with begin_immediate(engine) as conn:
        state = _state(conn)
        cursor = state[0] if state else 0
        head = int(conn.execute(text("SELECT coalesce(max(seq), 0) FROM events")).scalar_one())
        entries_seq = int(
            conn.execute(text("SELECT coalesce(max(seq), 0) FROM entries")).scalar_one()
        )
        applied = conn.execute(
            text("SELECT count(*) FROM events WHERE seq > :c AND type IN (:t, :u)"),
            {"c": cursor, "t": TRIGGERS[0], "u": TRIGGERS[1]},
        ).scalar_one()
        if force:
            reason = "forced"
        elif state is None:
            reason = "first"
        elif applied:
            reason = "events"
        elif state[1] != entries_seq:
            reason = "entries"
        elif state[2] != as_of.isoformat():
            reason = "as_of"
        else:
            return Refresh(False, 0, "current")
        rows = compute(conn, as_of)
        at = now_iso()
        conn.execute(text("DELETE FROM snapshots"))
        if rows:
            conn.execute(
                text(
                    "INSERT INTO snapshots (on_date, net_worth_minor, deposits_cum_minor, "
                    "by_envelope_json, by_account_json, computed_at) VALUES "
                    "(:on_date, :net_worth_minor, :deposits_cum_minor, :by_envelope_json, "
                    ":by_account_json, :at)"
                ),
                [{**r, "at": at} for r in rows],
            )
        conn.execute(
            text(
                "INSERT INTO snapshot_state (id, event_cursor, entries_seq, as_of, computed_at) "
                "VALUES (1, :c, :e, :d, :at) ON CONFLICT (id) DO UPDATE SET "
                "event_cursor = excluded.event_cursor, entries_seq = excluded.entries_seq, "
                "as_of = excluded.as_of, computed_at = excluded.computed_at"
            ),
            {"c": head, "e": entries_seq, "d": as_of.isoformat(), "at": at},
        )
    log.info("snapshots.refreshed", rows=len(rows), reason=reason)
    return Refresh(True, len(rows), reason)


MAX_LIVE_POINTS = 400
_STEP_DAYS = {"day": 1, "week": 7}


def steps(date_from: str, date_to: str, step: str) -> list[str]:
    """Dates de `date_to` en remontant de `step` jusqu'à `date_from`, dans l'ordre : la
    dernière est toujours `date_to`. Vide si l'intervalle est inversé."""
    start, end = date.fromisoformat(date_from), date.fromisoformat(date_to)
    out: list[str] = []
    d = end
    while d >= start and len(out) <= MAX_LIVE_POINTS:
        out.append(d.isoformat())
        d -= timedelta(days=_STEP_DAYS[step])
    return out[::-1]


def live_history(conn: Connection, dates: list[str]) -> dict[str, Any]:
    """Même forme que `history`, calculée à la demande (pas jour ou semaine, non stocké)."""
    ccy = base_currency()
    return {
        "currency": ccy,
        "as_of": dates[-1],
        "items": [
            {
                "on_date": v.on_date,
                "net_worth": money(v.net_worth, ccy),
                "deposits_cum": money(v.deposits, ccy),
                "by_envelope": {k: money(x, ccy) for k, x in v.by_envelope.items()},
                "by_account": {k: money(x, ccy) for k, x in v.by_account.items()},
            }
            for v in valuation.series(conn, dates)
        ],
    }


def stored(conn: Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            "SELECT on_date, net_worth_minor, deposits_cum_minor, by_envelope_json, "
            "by_account_json FROM snapshots ORDER BY on_date"
        )
    ).fetchall()
    return [
        {
            "on_date": r[0],
            "net_worth_minor": int(r[1]),
            "deposits_cum_minor": int(r[2]),
            "by_envelope_json": r[3],
            "by_account_json": r[4],
        }
        for r in rows
    ]


def history(conn: Connection, date_from: str | None, date_to: str | None) -> dict[str, Any]:
    rows = conn.execute(
        text(
            "SELECT on_date, net_worth_minor, deposits_cum_minor, by_envelope_json, "
            "by_account_json FROM snapshots WHERE (:f IS NULL OR on_date >= :f) "
            "AND (:t IS NULL OR on_date <= :t) ORDER BY on_date"
        ),
        {"f": date_from, "t": date_to},
    ).fetchall()
    state = _state(conn)
    ccy = base_currency()
    return {
        "currency": ccy,
        "as_of": state[2] if state else None,
        "items": [
            {
                "on_date": r[0],
                "net_worth": money(r[1], ccy),
                "deposits_cum": money(r[2], ccy),
                "by_envelope": {k: money(v, ccy) for k, v in json.loads(r[3]).items()},
                # valeur de chaque compte, pour une courbe filtrée (objectif, institution…)
                "by_account": {k: money(v, ccy) for k, v in json.loads(r[4]).items()},
            }
            for r in rows
        ],
    }
