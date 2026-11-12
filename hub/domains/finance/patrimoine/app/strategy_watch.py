"""Stratégies : la vérification de nuit. Une fois par jour, pour chaque stratégie active :
d'abord constater ce que le journal montre depuis l'étape en cours (elle se coche seule), puis
regarder si une nouvelle étape est atteinte, l'ouvrir et demander une notification. Une étape
à la fois, une alerte par étape (un seul rappel pour un achat régulier), jamais d'ordre.

La notification passe par un service tiers : son texte est générique, sans actif ni montant ;
le lien ouvre l'étape dans l'app."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import Connection, text

from hub.domains.finance.patrimoine.app import strategies
from hub.domains.finance.patrimoine.app.strategies import Step, Strategy, Today
from hub.domains.finance.patrimoine.model import strategy as rules
from hub.domains.finance.registre.app import ledger
from hub.kernel import canonical
from hub.kernel.clock import now_iso
from hub.kernel.ids import new_id, urn

NOTICE = {
    "ladder": "Stratégie : un palier est atteint",
    "recurring": "Stratégie : c'est le jour d'un achat prévu",
    "dip": "Stratégie : une grosse baisse est là",
    "reminder": "Stratégie : un achat prévu n'est pas encore au journal",
}


@dataclass(frozen=True)
class Opened:
    """Une étape ouverte (ou rappelée) cette nuit."""

    step_id: str
    kind: str
    reminder: bool = False


def _notify(conn: Connection, step_id: str, notice: str) -> None:
    ledger.append_event(
        conn,
        "notify.request",
        urn("finance", "strategy", step_id),
        {
            "title": NOTICE[notice],
            "body": "Le détail est dans l'app.",
            "tags": "bell",
            "click": f"/#strategy={step_id}",
        },
    )


def _update(conn: Connection, step_id: str, **cols: object) -> None:
    sets = ", ".join(f"{c} = :{c}" for c in cols)  # noms de colonnes fixés par l'appelant
    conn.execute(
        text(f"UPDATE strategy_steps SET {sets}, updated_at = :at WHERE id = :id"),  # noqa: S608
        {**cols, "at": now_iso(), "id": step_id},
    )


def _insert(
    conn: Connection,
    s: Strategy,
    key: str,
    day: str,
    planned: int | None,
    detail: dict[str, object],
    *,
    done: int = 0,
) -> str | None:
    """Ouvre l'étape, ou la pose déjà faite si le journal la montre (`done` atteint le prévu).
    None : cette clé a déjà eu son étape."""
    seen = rules.settled(done, planned)
    step_id = new_id()
    made = conn.execute(
        text(
            "INSERT OR IGNORE INTO strategy_steps (id, strategy_id, step_key, state, opened_on, "
            "planned_minor, done_minor, detail_json, closed_on, closed_by, created_at, updated_at) "
            "VALUES (:id, :s, :k, :state, :on, :p, :done, :d, :closed, :by, :at, :at)"
        ),
        {
            "id": step_id,
            "s": s.id,
            "k": key,
            "state": "done" if seen else "open",
            "on": day,
            "p": planned,
            "done": done,
            "d": canonical.dumps(detail),
            "closed": day if seen else None,
            "by": "journal" if seen else None,
            "at": now_iso(),
        },
    )
    return step_id if made.rowcount and not seen else None


def _since(s: Strategy, step: Step) -> str:
    """Depuis quand le journal compte pour cette étape : un achat régulier fait quelques jours
    avant l'échéance compte pour elle."""
    if s.kind != "recurring":
        return step.opened_on
    due = date.fromisoformat(str(step.detail.get("due", step.opened_on)))
    return (due - timedelta(days=rules.EARLY_DAYS)).isoformat()


def _settle(conn: Connection, s: Strategy, step: Step, now: Today) -> Opened | None:
    """Constate le journal sur l'étape en cours. Rend un rappel à envoyer, s'il y en a un."""
    since = _since(s, step)
    done = now.sold(s.scope, since) if s.kind == "ladder" else now.bought(s.scope, since)
    if rules.settled(done, step.planned):
        _update(
            conn, step.id, state="done", done_minor=done, closed_on=now.day, closed_by="journal"
        )
        return None
    if done != step.done:
        _update(conn, step.id, done_minor=done)
    if s.kind != "recurring":
        return None
    due = date.fromisoformat(str(step.detail.get("due", step.opened_on)))
    key = rules.recurring_key(
        str(s.params["cadence"]),
        rules.recurring_due(str(s.params["cadence"]), s.number("day"), now.today),
    )
    if key != step.key:  # l'échéance suivante est là : celle-ci est passée
        _update(conn, step.id, state="skipped", closed_on=now.day, closed_by="expired")
        return None
    late = (now.today - due).days >= rules.REMIND_AFTER_DAYS
    if step.state == "open" and late and not step.detail.get("reminded"):
        _update(conn, step.id, detail_json=canonical.dumps({**step.detail, "reminded": True}))
        return Opened(step.id, s.kind, reminder=True)
    return None


def _reach(conn: Connection, s: Strategy, mine: list[Step], now: Today) -> str | None:
    """Ouvre l'étape atteinte aujourd'hui, s'il y en a une ; rend son identifiant."""
    if s.kind == "ladder":
        level = now.level(s.scope)
        closed = frozenset(int(x.key[1:]) for x in mine)
        tier = rules.ladder_next(s.tiers(), closed, level.ratio)
        if tier is None:
            return None
        detail: dict[str, object] = {
            "at_pct": tier.at_pct,
            "sell_pct": tier.sell_pct,
            "ratio_pct": str(round(level.ratio or 0, 1)),
        }
        planned = rules.planned_sale(level.value, tier.sell_pct)
        return _insert(conn, s, f"t{tier.at_pct}", now.day, planned, detail)
    amount = s.number("amount_minor")
    if s.kind == "recurring":
        cadence = str(s.params["cadence"])
        due = rules.recurring_due(cadence, s.number("day"), now.today)
        if due.isoformat() < s.created_on:
            return None  # rien n'est dû avant le jour où la stratégie a été écrite
        early = (due - timedelta(days=rules.EARLY_DAYS)).isoformat()
        return _insert(
            conn,
            s,
            rules.recurring_key(cadence, due),
            now.day,
            amount,
            {"due": due.isoformat()},
            done=now.bought(s.scope, max(early, s.created_on)),
        )
    d = now.dip(s.scope, s.number("window_days"))
    last = max((x.opened_on for x in mine), default=None)
    if d is None or not rules.dip_reached(d, s.number("drop_pct"), last):
        return None
    detail = {"peak_on": d.peak_on, "drop_pct": str(round(d.drop_pct, 1))}
    return _insert(conn, s, f"p{d.peak_on}", now.day, amount, detail)


def run(conn: Connection, today: date) -> list[Opened]:
    """La vérification du jour, dans la transaction de l'appelant. La relancer le même jour ne
    rouvre ni ne renotifie rien."""
    now = Today(conn, today)
    by_strategy = strategies.steps(conn)
    out: list[Opened] = []
    for s in strategies.read(conn):
        if s.status != "active":
            continue
        mine = by_strategy.get(s.id, [])
        pending = next((x for x in mine if x.state in strategies.PENDING), None)
        if pending is not None:
            reminder = _settle(conn, s, pending, now)
            if reminder is not None:
                _notify(conn, reminder.step_id, "reminder")
                out.append(reminder)
            mine = strategies.steps(conn, s.id).get(s.id, [])
            if any(x.state in strategies.PENDING for x in mine):
                continue  # une étape à la fois
        step_id = _reach(conn, s, mine, now)
        if step_id is not None:
            _notify(conn, step_id, s.kind)
            out.append(Opened(step_id, s.kind))
    return out
