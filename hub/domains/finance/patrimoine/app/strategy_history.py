"""Achat régulier : les échéances passées, lues dans le journal. Une stratégie repérée par le hub
(strategy_detect.py) commence au premier achat de la série, pas au jour où on la valide : à la
création, chaque échéance déjà passée est posée tenue (le journal montre l'achat) ou passée. La
même lecture sert à la carte « À valider », qui montre ce que le hub a vu."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import Connection, text

from hub.domains.finance.patrimoine.app.strategies import Strategy, Today
from hub.domains.finance.patrimoine.model import strategy as rules
from hub.kernel import canonical
from hub.kernel.clock import now_iso
from hub.kernel.ids import new_id

MAX_PERIODS = 120  # dix ans de mois : une borne, jamais atteinte par une série repérée


@dataclass(frozen=True)
class Period:
    due: date
    done: int  # ce que le journal montre pour cette échéance, centimes de la devise de base


def first_due(cadence: str, day: int, first_buy: date) -> date:
    """L'échéance à laquelle compte un premier achat (fait jusqu'à trois jours avant elle)."""
    return rules.recurring_due(cadence, day, first_buy + timedelta(days=rules.EARLY_DAYS))


def dues(cadence: str, day: int, since: date, today: date) -> list[date]:
    """Les échéances de `since` à la dernière au plus tard aujourd'hui, comprises."""
    out: list[date] = []
    due = rules.recurring_due(cadence, day, since)
    if due < since:
        due = rules.recurring_next(cadence, day, since)
    while due <= today and len(out) < MAX_PERIODS:
        out.append(due)
        due = rules.recurring_next(cadence, day, due)
    return out


def periods(now: Today, scope: str, cadence: str, day: int, since: date) -> list[Period]:
    """Chaque échéance et ce que le journal montre pour elle : de trois jours avant elle à
    quatre jours avant la suivante."""
    out = []
    for due in dues(cadence, day, since, now.today):
        start = due - timedelta(days=rules.EARLY_DAYS)
        end = rules.recurring_next(cadence, day, due) - timedelta(days=rules.EARLY_DAYS + 1)
        out.append(Period(due, now.bought(scope, start.isoformat(), end.isoformat())))
    return out


def backfill(conn: Connection, s: Strategy, now: Today) -> int:
    """Pose les échéances déjà passées d'une stratégie repérée : tenue si le journal montre
    l'achat, passée sinon. L'échéance en cours reste à la vérification de nuit. Rend le nombre
    d'étapes posées."""
    cadence, day, amount = str(s.params["cadence"]), s.number("day"), s.number("amount_minor")
    current = rules.recurring_due(cadence, day, now.today)
    since = date.fromisoformat(s.created_on)
    made = 0
    for p in periods(now, s.scope, cadence, day, since):
        if p.due >= current:
            break
        seen = rules.settled(p.done, amount)
        made += conn.execute(
            text(
                "INSERT OR IGNORE INTO strategy_steps (id, strategy_id, step_key, state, "
                "opened_on, planned_minor, done_minor, detail_json, closed_on, closed_by, "
                "created_at, updated_at) VALUES (:id, :s, :k, :state, :on, :p, :done, :d, :on, "
                ":by, :at, :at)"
            ),
            {
                "id": new_id(),
                "s": s.id,
                "k": rules.recurring_key(cadence, p.due),
                "state": "done" if seen else "skipped",
                "on": p.due.isoformat(),
                "p": amount,
                "done": p.done,
                "d": canonical.dumps({"due": p.due.isoformat(), "past": True}),
                "by": "journal" if seen else "expired",
                "at": now_iso(),
            },
        ).rowcount
    return made
