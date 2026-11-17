"""« À venir » du mois (refonte du budget, lot C) : les charges fixes et les abonnements du mois
budgétaire, payés ou attendus, calculés ici une fois pour l'écran, l'assistant et les alertes.

- Une catégorie fixe (en mode « avec cible » ou « suivie sans cible ») est attendue au jour
  habituel (due.py) pour sa cible, sinon pour ce qu'elle coûte d'habitude (médiane des trois
  mois d'avant) ; sans cible, cette habitude arrondie à la dizaine est proposée comme cible.
- Les abonnements repérés (recurring.py) sont rattachés à leur catégorie : une catégorie fixe qui
  en a se lit par ses abonnements, un par un, et n'apparaît pas une seconde fois.
- État : `paid` (payée dans le mois), `due` (attendue), `late` (pas vue 3 jours après le jour
  habituel : la sentinelle `fixed_missing` le dit une fois par mois).
La portée `aggregates` n'a que les totaux : un montant de charge ou un nom d'abonnement
révélerait une écriture.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import Connection, text

from hub.domains.finance.classement.app import due
from hub.domains.finance.classement.app.insights import (
    category_groups,
    category_modes,
    category_names,
    lines_for,
    targets,
    yearly,
)
from hub.domains.finance.classement.app.recurring import MIN_COUNT, monthly
from hub.domains.finance.registre.model import period as period_rules
from hub.domains.finance.registre.model.amounts import in_base, previous_months
from hub.kernel.money import base_currency, exponent

LATE_DAYS = 3  # une charge fixe pas vue 3 jours après son jour habituel


@dataclass(frozen=True)
class Due:
    kind: str  # fixed | subscription
    category: str
    name: str  # la catégorie, ou le nom de l'abonnement
    on: str  # payée le, ou attendue le
    amount: int  # positif, devise de base
    status: str  # paid | due | late
    suggested_target: int | None = None


def _habit(conn: Connection, month: str) -> dict[str, int]:
    """Ce que chaque catégorie fixe coûte d'habitude : la médiane des trois mois d'avant."""
    found: dict[str, list[int]] = {}
    for m in previous_months(month, 3):
        for x in lines_for(conn, [m]):
            if x.group == "fixed" and x.minor < 0:
                found.setdefault(x.category, []).append(-x.minor)
    return {c: int(statistics.median(v)) for c, v in found.items()}


def _round_up(minor: int) -> int:
    ten: int = 10 * pow(10, exponent(base_currency()))
    return -(-minor // ten) * ten


def _subscriptions(conn: Connection, start: date, after: date) -> list[tuple[object, ...]]:
    return list(
        conn.execute(
            text(
                "SELECT label, category_id, cadence, amount_minor, currency, last_date, next_date "
                "FROM recurring WHERE active = 1 AND currency = :ccy "
                "AND ((next_date >= :s AND next_date < :e) OR (last_date >= :s AND last_date < :e))"
            ),
            {"ccy": base_currency(), "s": start.isoformat(), "e": after.isoformat()},
        )
    )


def _status(on: str, paid: bool, today: date) -> str:
    if paid:
        return "paid"
    return "late" if date.fromisoformat(on) + timedelta(days=LATE_DAYS) < today else "due"


def month_dues(conn: Connection, month: str, today: date) -> list[Due]:
    """Les charges fixes et abonnements du mois, payés ou attendus, par date."""
    start, after = period_rules.bounds(month)
    groups, modes, names = category_groups(conn), category_modes(conn), category_names(conn)
    goal, year = targets(conn, month), yearly(conn)
    paid_on = due.last_paid(conn, start, after)
    expected_on = due.expected(conn, month)
    habit = _habit(conn, month)
    out: list[Due] = []
    with_subs: set[str] = set()
    for label, cat, _cadence, amount, _ccy, last, nxt in _subscriptions(conn, start, after):
        paid = start.isoformat() <= str(last) < after.isoformat()
        if cat:
            with_subs.add(str(cat))
        out.append(
            Due(
                "subscription",
                str(cat or ""),
                str(label),
                str(last if paid else nxt),
                -int(str(amount)),
                _status(str(nxt), paid, today),
            )
        )
    for cat, grp in sorted(groups.items()):
        # une charge suivie à l'année (prime annuelle) est dans les provisions, pas attendue
        # chaque mois : sinon elle compterait deux fois dans le reste
        if grp != "fixed" or modes.get(cat) == "off_budget" or cat in with_subs or cat in year:
            continue
        on = paid_on.get(cat) or expected_on.get(cat)
        if on is None:
            continue  # ni payée ce mois ni d'habitude connue : rien à attendre
        target = goal[cat].monthly if cat in goal else None
        usual = habit.get(cat, 0)
        suggest = (
            _round_up(usual) if target is None and modes.get(cat) == "target" and usual else None
        )
        out.append(
            Due(
                "fixed",
                cat,
                names.get(cat, cat),
                on,
                target if target is not None else usual,
                _status(on, cat in paid_on, today),
                suggest,
            )
        )
    out.sort(key=lambda d: (d.on, d.name))
    return out


def upcoming(
    conn: Connection, month: str, today: date, *, aggregates_only: bool
) -> dict[str, object]:
    dues = month_dues(conn, month, today)
    left = [d for d in dues if d.status != "paid"]
    out: dict[str, object] = {
        "month": month,
        "currency": base_currency(),
        "count": len(dues),
        "paid_count": len(dues) - len(left),
        "due_total": in_base(sum(d.amount for d in left)),
        "late_count": sum(1 for d in left if d.status == "late"),
        "items": [],
    }
    if not aggregates_only:
        out["items"] = [
            {
                "kind": d.kind,
                "category": d.category or None,
                "name": d.name,
                "on": d.on,
                "amount": in_base(d.amount),
                "status": d.status,
                "suggested_target": in_base(d.suggested_target) if d.suggested_target else None,
            }
            for d in dues
        ]
    return out


def late_fixed(conn: Connection, today: date) -> list[Due]:
    """Charges fixes et abonnements du mois en cours pas vus 3 jours après leur jour habituel."""
    return [d for d in month_dues(conn, period_rules.month_of(today), today) if d.status == "late"]


def new_subscriptions(conn: Connection) -> list[tuple[str, str, str, int, str]]:
    """Abonnements tout juste repérés (le paiement minimal qui les fait reconnaître) : (clé,
    nom, rythme, coût mensuel, devise)."""
    rows = conn.execute(
        text(
            "SELECT key, label, cadence, amount_minor, currency, occurrences FROM recurring "
            "WHERE active = 1 ORDER BY key"
        )
    ).fetchall()
    return [
        (str(r[0]), str(r[1]), str(r[2]), monthly(int(r[3]), str(r[4]), str(r[2])), str(r[4]))
        for r in rows
        if int(r[5]) == (2 if r[2] == "yearly" else MIN_COUNT)
    ]
