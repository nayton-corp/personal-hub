"""Totaux par catégorie (ticket L1-10) : le résumé d'un mois et la tendance d'une catégorie.

Pour la portée `aggregates`, une catégorie qui compte moins de 3 écritures sur la période est
regroupée dans « Autres » : un total ne doit pas révéler une transaction."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import Connection, text

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
    """Total d'une catégorie sur une période, montant signé du registre."""

    category: str
    group: str
    minor: int
    count: int


# Les règles (lot 3) catégorisent à l'import ; ce qui reste sans catégorie compte, comme dans
# l'ancien script, en dépense variable s'il est négatif et en revenu sinon (la règle de départ
# « autres revenus » prend déjà presque tous les crédits). Il garde l'identifiant
# « a-categoriser » pour rester visible et se valider depuis l'écran « à catégoriser ».
_LINES = (
    "SELECT coalesce(v.category_id, :unc), "
    "CASE WHEN c.grp IS NOT NULL THEN c.grp WHEN v.amount_minor < 0 THEN 'variable' "
    "ELSE 'income' END, sum(v.amount_minor), count(DISTINCT v.entry_seq) "
    "FROM v_entry_allocation v JOIN entries e ON e.seq = v.entry_seq "
    "LEFT JOIN categories c ON c.id = v.category_id "
    "WHERE v.account_id IN {ids} AND v.currency = :ccy AND e.kind != 'opening' "
    "AND v.booking_date >= :s AND v.booking_date < :e GROUP BY 1, 2 ORDER BY 3, 1"
)


def period_lines(conn: Connection, start: str, end: str, currency: str | None = None) -> list[Line]:
    """Totaux par catégorie des comptes de budget, entre `start` inclus et `end` exclu, dans
    `currency` (la devise de base par défaut)."""
    currency = currency or base_currency()
    ids, params = in_list("a", budget_accounts(conn))
    rows = conn.execute(
        text(_LINES.format(ids=ids)),
        {**params, "unc": UNCATEGORIZED, "ccy": currency, "s": start, "e": end},
    ).fetchall()
    return [Line(r[0], r[1], int(r[2]), int(r[3])) for r in rows]


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
    lines = period_lines(conn, start, end, currency)
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
    }


def trend(
    conn: Connection, category: str | None, months: int, until: str, currency: str | None = None
) -> list[dict[str, Any]]:
    currency = currency or base_currency()
    first = shift_month(until, -(months - 1))
    start, _ = month_bounds(first)
    _, end = month_bounds(until)
    ids, params = in_list("a", budget_accounts(conn))
    cat_clause = (
        "AND v.category_id = :cat"
        if category
        else "AND (c.grp IN ('fixed', 'variable') OR (c.id IS NULL AND v.amount_minor < 0))"
    )
    rows = conn.execute(
        text(
            "SELECT v.booking_date, sum(v.amount_minor), count(*) "
            "FROM v_entry_allocation v JOIN entries e ON e.seq = v.entry_seq "
            "LEFT JOIN categories c ON c.id = v.category_id "
            f"WHERE v.account_id IN {ids} AND v.currency = :ccy AND e.kind = 'movement' "
            f"AND v.booking_date >= :s AND v.booking_date < :e {cat_clause} GROUP BY 1"
        ),
        {**params, "ccy": currency, "s": start, "e": end, "cat": category},
    ).fetchall()
    found: dict[str, tuple[int, int]] = {}
    for day, total, count in rows:  # par jour, rangé dans son mois budgétaire
        m = period.month_of(date.fromisoformat(day))
        t, c = found.get(m, (0, 0))
        found[m] = (t + int(total), c + int(count))
    series = []
    for i in range(months):
        m = shift_month(first, i)
        total, count = found.get(m, (0, 0))
        series.append({"month": m, "total": money(total, currency), "count": count})
    return series
