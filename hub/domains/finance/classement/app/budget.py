"""Budget et flux du mois (ticket L2-02) : chaque catégorie avec sa cible, ce qui est dépensé, son
état et sa projection à la fin du mois (model/pace.py, la même règle que les sentinelles,
audit M3), les totaux du budget, et les flux entre revenus, dépenses et épargne. Montants en
centimes, rapports en décimales texte ; le front affiche, il ne calcule pas."""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import Connection

from hub.domains.finance.classement.app import due
from hub.domains.finance.classement.app.insights import (
    EXPENSE_GROUPS,
    FLOW_GROUPS,
    category_groups,
    category_names,
    expense_budget,
    lines_for,
    merge_small,
    monthly_expenses,
    report_for,
    targets,
    totals_json,
    yearly,
)
from hub.domains.finance.classement.app.totals import Totals
from hub.domains.finance.classement.model import pace
from hub.domains.finance.registre.model import period as period_rules
from hub.domains.finance.registre.model.amounts import (
    days_left,
    in_base,
    period_months,
    previous_months,
    ratio,
    span,
    year_months,
)
from hub.kernel.money import base_currency, exponent


def flows(
    conn: Connection, month: str, *, aggregates_only: bool, period: str = "m"
) -> dict[str, Any]:
    months = period_months(month, period)
    lines = lines_for(conn, months)
    names = category_names(conn)
    t = Totals.of(lines)

    def items(group: str, sign: int) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = [
            {
                "category": x.category,
                "name": names.get(x.category, x.category),
                "total": in_base(sign * x.minor),
                "count": x.count,
            }
            for x in lines
            if x.group == group and x.minor != 0
        ]
        out.sort(key=lambda i: (-i["total"]["minor"], i["category"]))
        return merge_small(out) if aggregates_only else out

    groups = [
        {
            "group": g,
            "total": in_base(-sum(x.minor for x in lines if x.group == g)),
            "items": items(g, -1),
        }
        for g in FLOW_GROUPS
    ]
    return {
        "month": month,
        "period": period,
        "months": months,
        "currency": base_currency(),
        "income": in_base(t.income),
        "sources": items("income", 1),
        "groups": groups,
        "remainder": in_base(t.income - t.expenses - t.invested),
    }


def _clock(months: list[str], today: date) -> pace.Clock:
    start, _ = period_rules.bounds(months[0])
    _, after = period_rules.bounds(months[-1])
    return pace.clock(start, after, today)


def _money(minor: int | None) -> dict[str, Any] | None:
    return None if minor is None else in_base(minor)


def budget(
    conn: Connection, month: str, period: str, today: date, *, aggregates_only: bool
) -> dict[str, Any]:
    months = period_months(month, period)
    n = len(months)
    report = report_for(conn, months)
    lines = report.lines
    names = category_names(conn)
    goal = targets(conn, months[-1])
    groups = category_groups(conn)
    year = yearly(conn)
    clock = _clock(months, today)
    unit = 10 ** exponent(base_currency())  # une unité de la devise, en unités mineures
    # charges fixes : la date du dernier paiement de la période, et le jour où on les attend
    start, _ = period_rules.bounds(months[0])
    _, after = period_rules.bounds(months[-1])
    paid_on = due.last_paid(conn, start, after)
    expected_on = due.expected(conn, month) if period == "m" and clock.current else {}
    ytd: dict[str, int] = {}
    if year:
        for x in lines_for(conn, year_months(months[-1])):
            if x.category in year:
                ytd[x.category] = ytd.get(x.category, 0) - x.minor
    spent: dict[str, tuple[str, int, int]] = {}
    for x in lines:
        if x.group in EXPENSE_GROUPS:
            g, minor, count = spent.get(x.category, (x.group, 0, 0))
            spent[x.category] = (g, minor - x.minor, count + x.count)
    for cat in goal:
        if groups.get(cat) in EXPENSE_GROUPS and cat not in spent:
            spent[cat] = (groups[cat], 0, 0)
    out: list[dict[str, Any]] = []
    projection = 0
    targets_by_group = {"fixed": 0, "variable": 0}
    for cat, (group, minor, count) in spent.items():
        line: dict[str, Any] = {"category": cat, "name": names.get(cat, cat), "group": group}
        if cat in year:
            # suivie à l'année : comparée au cumul depuis janvier, pas au mois
            annual = goal[cat].annual if cat in goal else None
            done = ytd.get(cat, 0)
            line |= {
                "spent": in_base(minor),
                "count": count,
                "target": None,
                "ratio": None,
                "over": annual is not None and done > annual,
                "state": "over" if annual is not None and done > annual else "ok",
                "projected": None,
                "rest": None,
                "yearly": {
                    "target": _money(annual),
                    "spent": in_base(done),
                    "ratio": ratio(done, annual) if annual else None,
                    "from": year_months(months[-1])[0],
                },
            }
        else:
            target = goal[cat].monthly * n if cat in goal else None
            will = pace.projected(minor, group, target, clock)
            projection += will
            if target is not None:
                targets_by_group[group if group in targets_by_group else "variable"] += target
            state = pace.line_state(minor, group, target, clock, unit)
            line |= {
                "spent": in_base(minor),
                "count": count,
                "target": _money(target),
                "ratio": ratio(minor, target) if target else None,
                "over": state == "over",
                "state": state,
                "projected": in_base(will) if clock.current else None,
                "rest": _money(target - minor if target is not None else None),
            }
            if group == "fixed":
                line |= {"paid_on": paid_on.get(cat), "expected_on": expected_on.get(cat)}
        out.append(line)
    out.sort(key=lambda i: (EXPENSE_GROUPS.index(i["group"]), -i["spent"]["minor"], i["category"]))
    if aggregates_only:
        out = merge_small(out, key="spent")
    t = Totals.of(lines)
    monthly = expense_budget(conn, months[-1])
    total_budget = monthly * n if monthly is not None else None
    used = monthly_expenses(lines, year)
    rest = total_budget - used if total_budget is not None else None
    expected = pace.expected_share(targets_by_group["fixed"], targets_by_group["variable"], clock)
    whole = pace.period_state(total_budget, rest, projection if clock.current else None, clock)
    return {
        "month": month,
        "period": period,
        "months": months,
        "currency": base_currency(),
        "lines": out,
        "income": in_base(t.income),
        "expenses": in_base(t.expenses),
        "budget": _money(total_budget),
        # le reste à vivre ne compte que les catégories suivies au mois
        "budgeted_expenses": in_base(used),
        "rest_to_live": _money(rest),
        "days_left": days_left(month, today) if period == "m" else 0,
        "start": span(months)[0],
        "end": span(months)[1],
        "over_count": sum(1 for i in out if i.get("over")),
        # le rythme, l'attendu à ce jour, la projection et l'état : calculés ici, affichés là-bas
        "current": clock.current,
        "pace": ratio(*clock.fraction) if clock.fraction else None,
        "expected": ratio(*expected) if expected else None,
        "projection": in_base(projection) if clock.current else None,
        "state": {
            "kind": whole,
            "over_by": _money(-rest if rest is not None and rest < 0 else None),
        },
        "missing_fx": [m.public() for m in report.missing_fx],
    }


def budget_totals(conn: Connection, month: str, period: str) -> dict[str, Any]:
    months = period_months(month, period)
    lines = lines_for(conn, months)
    t = Totals.of(lines)
    monthly = expense_budget(conn, months[-1])
    total_budget = monthly * len(months) if monthly is not None else None
    used = monthly_expenses(lines, yearly(conn))
    return {
        "month": month,
        "period": period,
        "months": months,
        "start": span(months)[0],
        "end": span(months)[1],
        "currency": base_currency(),
        **totals_json(t),
        "budget": in_base(total_budget) if total_budget is not None else None,
        "budget_used": ratio(used, total_budget) if total_budget else None,
    }


def budget_months(conn: Connection, month: str, count: int) -> dict[str, Any]:
    """Les totaux de chaque mois, avec son budget d'alors et ce qui en a été dépensé : le même
    périmètre que le reste à vivre (hors catégories suivies à l'année), pour que la tendance
    dise « au-dessus du budget » comme l'écran du mois (audit du 10/11, B6)."""
    months = [*previous_months(month, count - 1), month]
    year = yearly(conn)
    series = []
    for m in months:
        lines = lines_for(conn, [m])
        goal = expense_budget(conn, m)
        used = monthly_expenses(lines, year)
        series.append(
            {
                "month": m,
                **totals_json(Totals.of(lines)),
                "budget": _money(goal),
                "budgeted_expenses": in_base(used),
                "over": _money(max(0, used - goal) if goal is not None else None),
            }
        )
    return {"currency": base_currency(), "series": series}
