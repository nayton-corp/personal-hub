"""Plan du mois (refonte du budget, lot A) : revenus attendus, épargne visée, non attribué, reste
du mois et par jour, et les dépenses cumulées jour par jour pour la courbe de l'écran.

- Revenus attendus : le montant saisi en vigueur au début du mois (`plan_income`), sinon la
  moyenne des revenus des trois mois complets d'avant (les mois sans revenu n'y entrent pas).
- Épargne visée : la somme des cibles posées sur les catégories d'épargne.
- Non attribué : revenus attendus − épargne visée − cibles des dépenses (une cible annuelle
  pour son douzième). Négatif : le plan dépasse les revenus.
- Reste du mois (H1) : revenus attendus − épargne visée − dépensé − ce qui est encore attendu
  (charges fixes du mois pas encore passées, upcoming.py) − le douzième des
  cibles annuelles (les catégories suivies à l'année ont leur enveloppe : leur dépense n'entre
  pas dans le dépensé) ; sans revenus attendus, cibles − dépensé (le reste à vivre d'avant).
- Par jour : le reste ÷ les jours restants, aujourd'hui compris ; rien si le reste est négatif.
Montants en centimes de la devise de base ; le front affiche, il ne calcule pas.
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import Connection, text

from hub.domains.finance.classement.app import upcoming
from hub.domains.finance.classement.app.insights import (
    Target,
    category_groups,
    category_names,
    lines_for,
    off_budget,
    targets,
    yearly,
)
from hub.domains.finance.classement.app.totals import EXPENSE_GROUPS, Line, Totals, scope_clause
from hub.domains.finance.registre.app.fx import FxTable
from hub.domains.finance.registre.model import period as period_rules
from hub.domains.finance.registre.model.amounts import (
    UNCATEGORIZED,
    in_base,
    previous_months,
    shift_month,
)
from hub.kernel.money import base_currency

AVERAGE_MONTHS = 3  # mois complets pris pour la moyenne des revenus


def entered_income(conn: Connection, month: str) -> tuple[int, int | None] | None:
    """(seq, montant) de la dernière saisie en vigueur au début du mois ; None sans saisie. Un
    montant None revient à la moyenne."""
    row = conn.execute(
        text(
            "SELECT seq, amount_minor FROM plan_income WHERE currency = :ccy "
            "AND valid_from <= :m ORDER BY seq DESC LIMIT 1"
        ),
        {"ccy": base_currency(), "m": f"{month}-01"},
    ).first()
    return None if row is None else (int(row[0]), None if row[1] is None else int(row[1]))


def average_income(conn: Connection, month: str) -> int | None:
    found = [
        income
        for m in previous_months(month, AVERAGE_MONTHS)
        if (income := Totals.of(lines_for(conn, [m])).income) > 0
    ]
    return (sum(found) + len(found) // 2) // len(found) if found else None


def expected_income(conn: Connection, month: str) -> tuple[int | None, str | None]:
    """(montant, origine) : `set` saisi, `average` moyenne des mois d'avant, (None, None) sans
    rien pour en juger."""
    entered = entered_income(conn, month)
    if entered is not None and entered[1] is not None:
        return entered[1], "set"
    average = average_income(conn, month)
    return (average, "average") if average is not None else (None, None)


def savings_targets(conn: Connection, month: str, groups: dict[str, str]) -> dict[str, Target]:
    return {c: t for c, t in targets(conn, month).items() if groups.get(c) == "savings"}


def plan_numbers(
    income: int | None,
    savings: int,
    targeted: int,
    used: int,
    fallback_rest: int | None,
    reserved: int = 0,
) -> tuple[int | None, int | None]:
    """(non attribué, reste du mois) ; `reserved` : ce qui est déjà promis (charges attendues,
    provisions annuelles) ; `fallback_rest` sert sans revenus attendus."""
    if income is None:
        return None, fallback_rest
    return income - savings - targeted, income - savings - used - reserved


def per_day(rest: int | None, days_left: int, current: bool) -> int | None:
    """Le reste ÷ les jours restants, aujourd'hui compris (`days_left` les compte après)."""
    if rest is None or rest < 0 or not current:
        return None
    return rest // (days_left + 1)


# dépenses par jour et par catégorie, dans le périmètre du budget (totals._SCOPE)
_DAILY = (
    "SELECT v.booking_date, coalesce(v.category_id, :unc), "
    "CASE WHEN c.grp IS NOT NULL THEN c.grp WHEN v.amount_minor < 0 THEN 'variable' "
    "ELSE 'income' END, sum(v.amount_minor), v.currency "
    "FROM v_entry_allocation v JOIN entries e ON e.seq = v.entry_seq "
    "JOIN accounts a ON a.id = v.account_id LEFT JOIN categories c ON c.id = v.category_id "
    "WHERE {scope} AND e.kind != 'opening' AND v.booking_date >= :s AND v.booking_date < :e "
    "GROUP BY 1, 2, 3, 5"
)


def daily(conn: Connection, month: str, skip: frozenset[str], until: date | None) -> list[int]:
    """Dépensé cumulé à la fin de chaque jour du mois, hors catégories `skip` (suivies à
    l'année, hors budget), jusqu'à `until` compris (le mois entier sans lui). Comme le dépensé
    du budget, une catégorie remboursée au-delà de son coût ne descend pas sous 0 ; le dernier
    point vaut ce dépensé."""
    start, after = period_rules.bounds(month)
    last = after - timedelta(days=1) if until is None else min(until, after - timedelta(days=1))
    if last < start:
        return []
    scope, params = scope_clause(conn)
    rows = conn.execute(
        text(_DAILY.format(scope=scope)),
        {
            **params,
            "unc": UNCATEGORIZED,
            "s": start.isoformat(),
            "e": (last + timedelta(days=1)).isoformat(),
        },
    ).fetchall()
    base = base_currency()
    fx: FxTable | None = None
    by_day: dict[str, dict[str, int]] = {}
    for day, cat, grp, total, ccy in rows:
        if grp not in EXPENSE_GROUPS or cat in skip:
            continue
        minor = int(total)
        if ccy != base:
            fx = fx or FxTable(conn)
            converted = fx.to_base(minor, str(ccy), str(day))
            if converted is None:
                continue  # sans change ce jour-là : le budget le signale déjà (missing_fx)
            minor = converted
        slot = by_day.setdefault(str(day), {})
        slot[str(cat)] = slot.get(str(cat), 0) - minor
    running: dict[str, int] = {}
    out: list[int] = []
    day = start
    while day <= last:
        for cat, spent in by_day.get(day.isoformat(), {}).items():
            running[cat] = running.get(cat, 0) + spent
        out.append(sum(max(0, v) for v in running.values()))
        day += timedelta(days=1)
    return out


def month_plan(
    conn: Connection,
    months: list[str],
    lines: list[Line],
    *,
    used: int,
    budget: int | None,
    provisions: int,
    today: date | None,
    days_left: int,
    aggregates_only: bool,
) -> dict[str, object]:
    """Le plan de la période (`plan`), et pour un mois seul sa courbe (`daily`, `prev_daily`) :
    `used` est le dépensé hors catégories annuelles, `budget` la somme des cibles du mois,
    `provisions` le douzième des cibles annuelles, `today` le jour d'aujourd'hui si la période
    est en cours. La portée `aggregates` n'a ni courbe ni détail par catégorie d'épargne : un
    point ou une ligne pourrait révéler une transaction."""
    n, month = len(months), months[-1]
    groups = category_groups(conn)
    skip = yearly(conn) | off_budget(conn)
    names = category_names(conn)
    income, source = expected_income(conn, month)
    expected = income * n if income is not None else None
    saving = savings_targets(conn, month, groups)
    put = {x.category: -x.minor for x in lines if x.group == "savings"}
    savings = sum(t.monthly for t in saving.values()) * n
    targeted = (budget or 0) + provisions
    fallback = budget - used if budget is not None else None
    current = today is not None
    # le mois en cours : ce qui est encore attendu ; un mois clos n'attend plus rien
    pending = (
        sum(d.amount for d in upcoming.month_dues(conn, month, today) if d.status != "paid")
        if today is not None and n == 1
        else 0
    )
    unassigned, rest = plan_numbers(
        expected, savings, targeted, used, fallback, reserved=pending + provisions
    )
    plan: dict[str, object] = {
        "income": _money(expected),
        "income_source": source,
        "savings": in_base(savings),
        "targets": in_base(targeted),
        "pending": in_base(pending),
        "provisions": in_base(provisions),
        "unassigned": _money(unassigned),
        "rest": _money(rest),
        "per_day": _money(per_day(rest, days_left, current and n == 1)),
        "savings_lines": []
        if aggregates_only
        else [
            {
                "category": c,
                "name": names.get(c, c),
                "target": in_base(t.monthly * n),
                "done": in_base(max(0, put.get(c, 0))),
            }
            for c, t in sorted(saving.items())
        ],
    }
    curve = n == 1 and not aggregates_only
    return {
        "plan": plan,
        "daily": daily(conn, month, skip, today) if curve else [],
        "prev_daily": daily(conn, shift_month(month, -1), skip, None) if curve else [],
    }


def _money(minor: int | None) -> dict[str, object] | None:
    return None if minor is None else in_base(minor)
