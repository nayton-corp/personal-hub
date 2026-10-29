"""Sentinelles (lot 7) : tâches de nuit déterministes qui rendent le hub proactif sans aucune
autonomie. Elles lisent le registre, lèvent une alerte une seule fois par occasion et demandent
une notification au cœur (événement `notify.request`, texte sans montant). Aucun modèle n'y
intervient, et rien n'est modifié dans le registre.

Premières sentinelles :
- budget dépassé, ou qui va l'être au rythme du mois (dépenses variables seulement : un loyer
  payé le 1er ne se projette pas) ;
- abonnement dont le dernier paiement dépasse le montant habituel ;
- marge 3a de l'année pas encore versée, en novembre et en décembre.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import Connection, text

from hub.core import canonical
from hub.core.clock import now_iso
from hub.core.ids import urn
from hub.domains.finance import insights, ledger, period
from hub.domains.finance.reads import money

MIN_DAY_FOR_PROJECTION = 7  # avant le 7, une projection linéaire ne dit rien
LIKELY_MARGIN_PCT = 10  # « va dépasser » : projection au-delà de la cible + 10 %
RECURRING_UP_PCT = 5  # hausse d'abonnement : au moins 5 % …
RECURRING_UP_MIN = 100  # … et au moins 1 franc
PILLAR3A_MONTHS = (11, 12)
ALERT_DAYS = 31  # ce que l'app montre


@dataclass(frozen=True)
class Projection:
    category: str
    name: str
    group: str
    spent: int  # dépense du mois en positif, centimes
    target: int
    projected: int
    over: bool
    likely_over: bool


def budget_projection(conn: Connection, month: str, today: date) -> list[Projection]:
    """Catégories de dépense qui ont une cible : dépensé, projection à fin de mois."""
    goal = insights.targets(conn, month)
    groups = insights.category_groups(conn)
    names = insights.category_names(conn)
    year = insights.yearly(conn)
    spent: dict[str, int] = {}
    for x in insights.lines_for(conn, [month]):
        if x.group in insights.EXPENSE_GROUPS:
            spent[x.category] = spent.get(x.category, 0) - x.minor
    start, after = period.bounds(month)
    current = period.month_of(today) == month
    elapsed, length = (today - start).days + 1, (after - start).days
    out = []
    for cat, target in sorted(goal.items()):
        group = groups.get(cat)
        if group not in insights.EXPENSE_GROUPS or target <= 0 or cat in year:
            continue  # une catégorie suivie à l'année n'a pas de cible du mois (voir _yearly)
        value = max(0, spent.get(cat, 0))
        projected = value
        if current and group == "variable" and elapsed >= MIN_DAY_FOR_PROJECTION:
            projected = value * length // elapsed
        over = value > target
        likely = not over and current and projected * 100 > target * (100 + LIKELY_MARGIN_PCT)
        out.append(
            Projection(cat, names.get(cat, cat), group, value, target, projected, over, likely)
        )
    return out


@dataclass(frozen=True)
class Alert:
    key: str
    kind: str
    title: str  # pour l'app : nomme la catégorie ou l'abonnement, jamais un montant
    notice: str  # pour la notification (ntfy, un service tiers) : générique
    detail: dict[str, Any]


def _budget(conn: Connection, today: date) -> list[Alert]:
    month = period.month_of(today)
    out = []
    for p in budget_projection(conn, month, today):
        detail = {
            "category": p.category,
            "month": month,
            "spent": insights.in_base(p.spent),
            "target": insights.in_base(p.target),
            "projected": insights.in_base(p.projected),
        }
        if p.over:
            out.append(
                Alert(
                    f"budget-over:{p.category}:{month}",
                    "budget_over",
                    f"Budget {p.name} dépassé",
                    "Budget : une cible du mois est dépassée",
                    detail,
                )
            )
        elif p.likely_over:
            out.append(
                Alert(
                    f"budget-likely:{p.category}:{month}",
                    "budget_likely",
                    f"Budget {p.name} : dépassement probable",
                    "Budget : une cible du mois sera probablement dépassée",
                    detail,
                )
            )
    return out + _yearly(conn, month)


def _yearly(conn: Connection, month: str) -> list[Alert]:
    """Cible annuelle dépassée par le cumul depuis janvier : une alerte par année."""
    year = insights.yearly(conn)
    if not year:
        return []
    goal = insights.targets(conn, month)
    names = insights.category_names(conn)
    done: dict[str, int] = {}
    for x in insights.lines_for(conn, insights.year_months(month)):
        if x.category in year:
            done[x.category] = done.get(x.category, 0) - x.minor
    out = []
    for cat in sorted(year):
        annual = goal.get(cat, 0) * 12
        if annual > 0 and done.get(cat, 0) > annual:
            out.append(
                Alert(
                    f"budget-over-year:{cat}:{month[:4]}",
                    "budget_over",
                    f"Budget annuel {names.get(cat, cat)} dépassé",
                    "Budget : une cible annuelle est dépassée",
                    {
                        "category": cat,
                        "month": month,
                        "spent": insights.in_base(done[cat]),
                        "target": insights.in_base(annual),
                        "projected": insights.in_base(done[cat]),
                    },
                )
            )
    return out


def _recurring(conn: Connection) -> list[Alert]:
    rows = conn.execute(
        text(
            "SELECT key, label, amount_minor, last_minor, currency, last_date, cadence "
            "FROM recurring WHERE active = 1 ORDER BY key"
        )
    ).fetchall()
    out = []
    for key, label, usual, last, ccy, last_date, cadence in rows:
        usual, last = abs(int(usual)), abs(int(last))
        rise = last - usual
        if rise < RECURRING_UP_MIN or rise * 100 < usual * RECURRING_UP_PCT:
            continue
        out.append(
            Alert(
                f"recurring-up:{key}:{last_date}",
                "recurring_up",
                f"Abonnement en hausse : {label}",
                "Un abonnement a augmenté",
                {
                    "merchant": key,
                    "label": label,
                    "cadence": cadence,
                    "usual": money(usual, ccy),
                    "last": money(last, ccy),
                    "last_date": last_date,
                },
            )
        )
    return out


def _pillar3a(conn: Connection, today: date, cap: int | None) -> list[Alert]:
    if today.month not in PILLAR3A_MONTHS:
        return []
    p = insights.pillar3a_year(conn, today.year, today, cap)
    if int(p["margin"]["minor"]) <= 0:
        return []
    return [
        Alert(
            f"pillar3a:{today.year}-{today.month:02d}",
            "pillar3a_margin",
            f"3e pilier : marge {today.year} pas encore versée",
            "3e pilier : il reste de la marge cette année",
            {"year": p["year"], "cap": p["cap"], "paid": p["paid"], "margin": p["margin"]},
        )
    ]


def evaluate(
    conn: Connection, today: date, *, pillar3a: bool = True, pillar3a_cap: int | None = None
) -> list[Alert]:
    p3 = _pillar3a(conn, today, pillar3a_cap) if pillar3a else []
    return _budget(conn, today) + _recurring(conn) + p3


def run(
    conn: Connection, today: date, *, pillar3a: bool = True, pillar3a_cap: int | None = None
) -> list[Alert]:
    """Lève les alertes nouvelles (dans la transaction de l'appelant) et demande leur
    notification ; une occasion déjà levée ne l'est plus."""
    raised = []
    for a in evaluate(conn, today, pillar3a=pillar3a, pillar3a_cap=pillar3a_cap):
        exists = conn.execute(text("SELECT 1 FROM alerts WHERE key = :k"), {"k": a.key}).first()
        if exists:
            continue
        conn.execute(
            text(
                "INSERT INTO alerts (key, kind, title, detail_json, on_date, created_at) "
                "VALUES (:k, :kind, :t, :d, :on, :at)"
            ),
            {
                "k": a.key,
                "kind": a.kind,
                "t": a.title,
                "d": canonical.dumps(a.detail),
                "on": today.isoformat(),
                "at": now_iso(),
            },
        )
        ledger.append_event(
            conn,
            "notify.request",
            urn("finance", "alert", hashlib.sha256(a.key.encode()).hexdigest()[:20]),
            {"title": a.notice, "body": "Le détail est dans l'app.", "tags": "bell"},
        )
        raised.append(a)
    return raised


def recent(conn: Connection, today: date, days: int = ALERT_DAYS) -> list[dict[str, Any]]:
    since = date.fromordinal(today.toordinal() - days).isoformat()
    rows = conn.execute(
        text(
            "SELECT key, kind, title, detail_json, on_date FROM alerts WHERE on_date >= :s "
            "ORDER BY on_date DESC, key"
        ),
        {"s": since},
    ).fetchall()
    return [
        {"key": r[0], "kind": r[1], "title": r[2], "detail": json.loads(r[3]), "on_date": r[4]}
        for r in rows
    ]
