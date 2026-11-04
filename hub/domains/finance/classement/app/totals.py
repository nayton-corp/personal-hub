"""Totaux par catégorie (ticket L1-10) : le résumé d'un mois et la tendance d'une catégorie.

Une écriture dans une autre devise (carte Revolut en euros) compte au change du jour de
l'écriture (audit C3) ; sans change ce jour-là, elle est laissée de côté et signalée
(`missing_fx`), jamais comptée pour 0 ni passée sous silence.

Pour la portée `aggregates`, une catégorie qui compte moins de 3 écritures sur la période est
regroupée dans « Autres » : un total ne doit pas révéler une transaction."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import Connection, text

from hub.domains.finance.registre.app.fx import FxTable
from hub.domains.finance.registre.app.reads import budget_accounts, in_list
from hub.domains.finance.registre.model import period
from hub.domains.finance.registre.model.amounts import (
    MIN_COUNT_FOR_AGGREGATES,
    OTHERS,
    UNCATEGORIZED,
    money,
    month_bounds,
    shift_month,
)
from hub.kernel.money import base_currency


def _merge_small(rows: list[dict[str, Any]], currency: str) -> list[dict[str, Any]]:
    kept = [r for r in rows if r["count"] >= MIN_COUNT_FOR_AGGREGATES]
    small = [r for r in rows if r["count"] < MIN_COUNT_FOR_AGGREGATES]
    if small:
        kept.append(
            {
                "category": OTHERS,
                "group": "mixed",
                "total": money(sum(r["total"]["minor"] for r in small), currency),
                "count": sum(r["count"] for r in small),
            }
        )
    return kept


@dataclass(frozen=True)
class Line:
    """Total d'une catégorie sur une période, montant signé dans la devise de base."""

    category: str
    group: str
    minor: int
    count: int


@dataclass(frozen=True)
class MissingFx:
    """Des écritures d'un jour dans une devise sans change : laissées de côté, à montrer."""

    currency: str
    on_date: str
    count: int

    def public(self) -> dict[str, Any]:
        return {"currency": self.currency, "on_date": self.on_date, "count": self.count}


@dataclass(frozen=True)
class Lines:
    lines: list[Line]
    missing_fx: list[MissingFx]


# Un compte de budget compte en entier. Un autre compte courant (l'épargne) ne compte que pour ses
# dépenses catégorisées : des impôts payés depuis l'épargne restent des impôts, mais ses
# intérêts, ses virements et ce qu'il a sans catégorie restent hors budget.
_SCOPE = "(v.account_id IN {ids} OR (a.kind = 'cash' AND c.grp IN ('fixed', 'variable')))"


def _scope(conn: Connection) -> tuple[str, dict[str, str]]:
    ids, params = in_list("a", budget_accounts(conn))
    return _SCOPE.format(ids=ids), params


# Les règles (lot 3) catégorisent à l'import ; ce qui reste sans catégorie compte, comme dans
# l'ancien script, en dépense variable s'il est négatif et en revenu sinon (la règle de départ
# « autres revenus » prend déjà presque tous les crédits). Il garde l'identifiant
# « a-categoriser » pour rester visible et se valider depuis l'écran « à catégoriser ».
# une ligne par catégorie et groupe dans la devise de base ; dans une autre devise, une ligne
# par jour, convertie ensuite au change de ce jour
_LINES = (
    "SELECT coalesce(v.category_id, :unc), "
    "CASE WHEN c.grp IS NOT NULL THEN c.grp WHEN v.amount_minor < 0 THEN 'variable' "
    "ELSE 'income' END, sum(v.amount_minor), count(DISTINCT v.entry_seq), v.currency, "
    "CASE WHEN v.currency = :ccy THEN '' ELSE v.booking_date END "
    "FROM v_entry_allocation v JOIN entries e ON e.seq = v.entry_seq "
    "JOIN accounts a ON a.id = v.account_id "
    "LEFT JOIN categories c ON c.id = v.category_id "
    "WHERE {scope} AND e.kind != 'opening' "
    "AND v.booking_date >= :s AND v.booking_date < :e GROUP BY 1, 2, 5, 6 ORDER BY 3, 1"
)


def period_report(conn: Connection, start: str, end: str, fx: FxTable | None = None) -> Lines:
    """Totaux par catégorie des comptes de budget (et des dépenses catégorisées des autres comptes
    courants, `_SCOPE`), entre `start` inclus et `end` exclu, dans la devise de base : une
    écriture en devise au change de son jour, sans change signalée et laissée de côté."""
    base = base_currency()
    scope, params = _scope(conn)
    rows = conn.execute(
        text(_LINES.format(scope=scope)),
        {**params, "unc": UNCATEGORIZED, "ccy": base, "s": start, "e": end},
    ).fetchall()
    found: dict[tuple[str, str], list[int]] = {}
    missing: dict[tuple[str, str], int] = {}
    for cat, grp, total, count, ccy, day in rows:
        minor = int(total)
        if ccy != base:
            if fx is None:
                fx = FxTable(conn)
            converted = fx.to_base(minor, str(ccy), str(day))
            if converted is None:
                key = (str(ccy), str(day))
                missing[key] = missing.get(key, 0) + int(count)
                continue
            minor = converted
        slot = found.setdefault((str(cat), str(grp)), [0, 0])
        slot[0] += minor
        slot[1] += int(count)
    lines = [Line(cat, grp, v[0], v[1]) for (cat, grp), v in found.items()]
    lines.sort(key=lambda x: (x.minor, x.category))
    return Lines(lines, [MissingFx(c, d, n) for (c, d), n in sorted(missing.items())])


def period_lines(conn: Connection, start: str, end: str, currency: str | None = None) -> list[Line]:
    """Les lignes de `period_report`, dans la devise de base (`currency` ne peut être qu'elle)."""
    if currency is not None and currency != base_currency():
        raise ValueError("les totaux sont dans la devise de base de l'instance")
    return period_report(conn, start, end).lines


@dataclass(frozen=True)
class Totals:
    income: int
    fixed: int  # dépenses, en positif
    variable: int
    invested: int  # vers les catégories d'épargne (3a, placements), en positif
    transfers: int
    uncategorized: int

    @property
    def expenses(self) -> int:
        return self.fixed + self.variable

    @property
    def savings(self) -> int:
        """Ce qui reste des revenus après les dépenses (épargne et placements compris)."""
        return self.income - self.expenses

    @classmethod
    def of(cls, lines: list[Line]) -> Totals:
        g: dict[str, int] = {}
        for x in lines:
            g[x.group] = g.get(x.group, 0) + x.minor
        return cls(
            income=g.get("income", 0),
            fixed=-g.get("fixed", 0),
            variable=-g.get("variable", 0),
            invested=-g.get("savings", 0),
            transfers=g.get("transfer", 0),
            uncategorized=sum(x.minor for x in lines if x.category == UNCATEGORIZED),
        )


def summary(
    conn: Connection, month: str, *, aggregates_only: bool, currency: str | None = None
) -> dict[str, Any]:
    currency = currency or base_currency()
    start, end = month_bounds(month)
    report = period_report(conn, start, end)
    lines = report.lines
    by_category = [
        {
            "category": x.category,
            "group": x.group,
            "total": money(x.minor, currency),
            "count": x.count,
        }
        for x in lines
    ]
    groups: dict[str, int] = {}
    for x in lines:
        groups[x.group] = groups.get(x.group, 0) + x.minor
    t = Totals.of(lines)
    if aggregates_only:
        by_category = _merge_small(by_category, currency)
    return {
        "month": month,
        "currency": currency,
        "income": money(t.income, currency),
        "expenses": money(t.expenses, currency),
        "savings": money(t.invested, currency),
        "transfers": money(t.transfers, currency),
        "uncategorized": money(t.uncategorized, currency),
        "by_group": {g: money(v, currency) for g, v in sorted(groups.items())},
        "by_category": by_category,
        "missing_fx": [m.public() for m in report.missing_fx],
    }


def trend(
    conn: Connection, category: str | None, months: int, until: str, currency: str | None = None
) -> list[dict[str, Any]]:
    currency = currency or base_currency()
    first = shift_month(until, -(months - 1))
    start, _ = month_bounds(first)
    _, end = month_bounds(until)
    scope, params = _scope(conn)
    cat_clause = (
        "AND v.category_id = :cat"
        if category
        else "AND (c.grp IN ('fixed', 'variable') OR (c.id IS NULL AND v.amount_minor < 0))"
    )
    rows = conn.execute(
        text(
            "SELECT v.booking_date, sum(v.amount_minor), count(*), v.currency "
            "FROM v_entry_allocation v JOIN entries e ON e.seq = v.entry_seq "
            "JOIN accounts a ON a.id = v.account_id "
            "LEFT JOIN categories c ON c.id = v.category_id "
            f"WHERE {scope} AND e.kind = 'movement' "
            f"AND v.booking_date >= :s AND v.booking_date < :e {cat_clause} GROUP BY 1, 4"
        ),
        {**params, "s": start, "e": end, "cat": category},
    ).fetchall()
    fx: FxTable | None = None
    found: dict[str, tuple[int, int]] = {}
    for day, total, count, ccy in rows:  # par jour, rangé dans son mois budgétaire
        minor = int(total)
        if ccy != currency:
            fx = fx or FxTable(conn)
            converted = fx.to_base(minor, str(ccy), str(day))
            if converted is None:
                continue  # sans change ce jour-là : hors de la tendance (le budget le signale)
            minor = converted
        m = period.month_of(date.fromisoformat(day))
        t, c = found.get(m, (0, 0))
        found[m] = (t + minor, c + int(count))
    series = []
    for i in range(months):
        m = shift_month(first, i)
        total, count = found.get(m, (0, 0))
        series.append({"month": m, "total": money(total, currency), "count": count})
    return series
