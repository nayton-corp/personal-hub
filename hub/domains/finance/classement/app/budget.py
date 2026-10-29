"""Budget et flux du mois (ticket L2-02) : chaque catégorie avec sa cible, ce qui est dépensé et la
projection à la fin du mois, les totaux du budget, et les flux entre revenus, dépenses et
épargne. Montants en centimes, rapports en décimales texte."""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import Connection

from hub.domains.finance.classement.app.insights import (
    EXPENSE_GROUPS,
    FLOW_GROUPS,
    category_groups,
    category_names,
    expense_budget,
    lines_for,
    merge_small,
    monthly_expenses,
    targets,
    totals_json,
    yearly,
)
from hub.domains.finance.classement.app.totals import Totals
from hub.domains.finance.registre.model.amounts import (
    days_left,
    in_base,
    period_months,
    previous_months,
    ratio,
    span,
    year_months,
)
from hub.kernel.money import base_currency


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


def budget(
    conn: Connection, month: str, period: str, today: date, *, aggregates_only: bool
) -> dict[str, Any]:
    months = period_months(month, period)
    n = len(months)
    lines = lines_for(conn, months)
    names = category_names(conn)
    goal = targets(conn, months[-1])
    groups = category_groups(conn)
    year = yearly(conn)
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
    for cat, (group, minor, count) in spent.items():
        line: dict[str, Any] = {"category": cat, "name": names.get(cat, cat), "group": group}
        if cat in year:
            # suivie à l'année : comparée au cumul depuis janvier, pas au mois
            annual = goal[cat] * 12 if cat in goal else None
            done = ytd.get(cat, 0)
            line |= {
                "spent": in_base(minor),
                "count": count,
                "target": None,
                "ratio": None,
                "over": annual is not None and done > annual,
                "yearly": {
                    "target": in_base(annual) if annual is not None else None,
                    "spent": in_base(done),
                    "ratio": ratio(done, annual) if annual else None,
                    "from": year_months(months[-1])[0],
                },
            }
        else:
            target = goal[cat] * n if cat in goal else None
            line |= {
                "spent": in_base(minor),
                "count": count,
                "target": in_base(target) if target is not None else None,
                "ratio": ratio(minor, target) if target else None,
                "over": target is not None and minor > target,
            }
        out.append(line)
    out.sort(key=lambda i: (EXPENSE_GROUPS.index(i["group"]), -i["spent"]["minor"], i["category"]))
    if aggregates_only:
        out = merge_small(out, key="spent")
    t = Totals.of(lines)
    monthly = expense_budget(conn, months[-1])
    total_budget = monthly * n if monthly is not None else None
    return {
        "month": month,
        "period": period,
        "months": months,
        "currency": base_currency(),
        "lines": out,
        "income": in_base(t.income),
        "expenses": in_base(t.expenses),
        "budget": in_base(total_budget) if total_budget is not None else None,
        # le reste à vivre ne compte que les catégories suivies au mois
        "budgeted_expenses": in_base(monthly_expenses(lines, year)),
        "rest_to_live": (
            in_base(total_budget - monthly_expenses(lines, year))
            if total_budget is not None
            else None
        ),
        "days_left": days_left(month, today) if period == "m" else 0,
        "start": span(months)[0],
        "end": span(months)[1],
        "over_count": sum(1 for i in out if i.get("over")),
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
    months = [*previous_months(month, count - 1), month]
    series = []
    for m in months:
        series.append({"month": m, **totals_json(Totals.of(lines_for(conn, [m])))})
    return {"currency": base_currency(), "series": series}
