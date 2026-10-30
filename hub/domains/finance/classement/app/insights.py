"""Chiffres de l'app (ticket L2-02) : les neuf calculs du dashboard prototype, côté serveur et
en centimes.

Le « mois en cours » vient toujours du paramètre `month` et « aujourd'hui » de l'appelant ;
rien n'est déduit des données. Le début d'année est le 31 décembre précédent. Les rapports
sont des décimales en texte (`"0.2534"`), jamais des flottants.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy import Connection, text

from hub.domains.finance.classement.app.totals import Line, Totals, period_lines
from hub.domains.finance.registre.app.reads import budget_accounts, in_list, last_data
from hub.domains.finance.registre.model import institutions
from hub.domains.finance.registre.model.amounts import (
    MIN_COUNT_FOR_AGGREGATES,
    OTHERS,
    UNCATEGORIZED,
    in_base,
    ratio,
    span,
)
from hub.kernel.money import base_currency

STALE_DAYS = 45
EPARGNE_3A = "epargne-3a"
PENSION_DEPOSITS = institutions.like_any(
    "bank_tx_code", institutions.prefixes(pension_deposit=True)
)
# plafond du 3e pilier A pour un salarié affilié à une caisse de pension, en centimes ;
# une année absente prend le dernier plafond connu, `[finance] pillar3a_cap_minor` le remplace
PILLAR_3A_CAP = {2024: 705_600, 2025: 725_800, 2026: 725_800}
EXPENSE_GROUPS = ("fixed", "variable")
FLOW_GROUPS = ("fixed", "variable", "savings")
NAMES_EXTRA = {UNCATEGORIZED: "À catégoriser", OTHERS: "Autres"}


# --- périodes ---------------------------------------------------------------------------------


# --- briques ----------------------------------------------------------------------------------


def category_names(conn: Connection) -> dict[str, str]:
    names = {r[0]: r[1] for r in conn.execute(text("SELECT id, name FROM categories"))}
    return {**names, **NAMES_EXTRA}


def targets(conn: Connection, month: str) -> dict[str, int]:
    """Cible mensuelle en vigueur au début du mois, par catégorie (la dernière ligne gagne)."""
    rows = conn.execute(
        text(
            "SELECT b.category_id, b.monthly_minor FROM budgets b "
            "WHERE b.currency = :ccy AND b.seq = (SELECT max(seq) FROM budgets "
            "WHERE category_id = b.category_id AND valid_from <= :m)"
        ),
        {"m": f"{month}-01", "ccy": base_currency()},
    )
    return {r[0]: int(r[1]) for r in rows}


def category_groups(conn: Connection) -> dict[str, str]:
    return {r[0]: r[1] for r in conn.execute(text("SELECT id, grp FROM categories"))}


def yearly(conn: Connection) -> frozenset[str]:
    """Catégories suivies à l'année (vacances, entretien) : leur cible mensuelle est le douzième
    de la cible annuelle, et elles sortent du budget et du reste à vivre du mois."""
    rows = conn.execute(text("SELECT category_id FROM budget_cadence WHERE cadence = 'year'"))
    return frozenset(str(r[0]) for r in rows)


def expense_budget(conn: Connection, month: str) -> int | None:
    groups, year = category_groups(conn), yearly(conn)
    found = {
        c: v
        for c, v in targets(conn, month).items()
        if groups.get(c) in EXPENSE_GROUPS and c not in year
    }
    return sum(found.values()) if found else None


def monthly_expenses(lines: list[Line], year: frozenset[str]) -> int:
    """Dépenses de la période hors catégories suivies à l'année, en positif."""
    return -sum(x.minor for x in lines if x.group in EXPENSE_GROUPS and x.category not in year)


def lines_for(conn: Connection, months: list[str]) -> list[Line]:
    start, end = span(months)
    return period_lines(conn, start, end, base_currency())


def merge_small(items: list[dict[str, Any]], key: str = "total") -> list[dict[str, Any]]:
    """Portée aggregates : une catégorie de moins de 3 écritures rejoint « Autres »."""
    kept = [i for i in items if i["count"] >= MIN_COUNT_FOR_AGGREGATES]
    small = [i for i in items if i["count"] < MIN_COUNT_FOR_AGGREGATES]
    if not small:
        return kept
    other: dict[str, Any] = {
        "category": OTHERS,
        "name": NAMES_EXTRA[OTHERS],
        key: in_base(sum(i[key]["minor"] for i in small)),
        "count": sum(i["count"] for i in small),
    }
    for extra in ("group",):
        if extra in small[0]:
            other[extra] = small[0][extra] if len({i[extra] for i in small}) == 1 else "mixed"
    if "target" in small[0]:
        tg = [i["target"]["minor"] for i in small if i["target"]]
        other["target"] = in_base(sum(tg)) if tg else None
        other["ratio"] = ratio(other[key]["minor"], sum(tg)) if tg else None
        other["over"] = bool(tg) and other[key]["minor"] > sum(tg)
    return [*kept, other]


def totals_json(t: Totals) -> dict[str, Any]:
    return {
        "income": in_base(t.income),
        "expenses": in_base(t.expenses),
        "fixed": in_base(t.fixed),
        "variable": in_base(t.variable),
        "savings": in_base(t.savings),
        "invested": in_base(t.invested),
        "rate": ratio(t.savings, t.income),
    }


def last_clbds(conn: Connection) -> list[tuple[str, str | None]]:
    rows = conn.execute(
        text(
            "SELECT a.id, (SELECT max(on_date) FROM checkpoints c WHERE c.account_id = a.id "
            "AND c.kind = 'CLBD') FROM accounts a WHERE a.kind = 'cash' AND a.closed_on IS NULL"
        )
    ).fetchall()
    return [(r[0], r[1]) for r in rows]


def stale_accounts(conn: Connection, today: date) -> int:
    """Comptes affichés dont la dernière donnée (écriture, position, solde de clôture) a plus de
    STALE_DAYS jours. Un compte encore jamais alimenté n'en fait pas partie."""
    limit = (today - timedelta(days=STALE_DAYS)).isoformat()
    ids = conn.execute(
        text("SELECT id FROM accounts WHERE closed_on IS NULL AND hidden = 0")
    ).scalars()
    return sum(1 for a in ids if (d := last_data(conn, a)) is not None and d < limit)


def to_categorize(conn: Connection) -> int:
    return int(
        conn.execute(
            text(
                # un côté de virement apparié n'attend pas de catégorie (lot 6, v_entry_shown)
                "SELECT count(*) FROM entries e LEFT JOIN v_entry_shown vc "
                "ON vc.entry_seq = e.seq WHERE vc.category_id IS NULL AND e.kind = 'movement'"
            )
        ).scalar_one()
    )


def pillar3a_year(
    conn: Connection, year: int, until: date, cap: int | None = None
) -> dict[str, Any]:
    """Versements 3a de l'année : ceux que VIAC a reçus (avis de versement) ou, à défaut, les
    paiements catégorisés « épargne 3a » sur les comptes courants ; le plus grand des deux,
    pour qu'un historique VIAC incomplet ou une catégorie manquante ne sous-estime rien."""
    if cap is None:
        known = [y for y in PILLAR_3A_CAP if y <= year] or [min(PILLAR_3A_CAP)]
        cap = PILLAR_3A_CAP[max(known)]
    period = {"ccy": base_currency(), "s": f"{year}-01-01", "e": until.isoformat()}
    ids, params = in_list("a", budget_accounts(conn))
    from_bank = -int(
        conn.execute(
            text(
                "SELECT coalesce(sum(amount_minor), 0) FROM v_entry_allocation "
                f"WHERE category_id = :c AND account_id IN {ids} AND currency = :ccy "
                "AND booking_date >= :s AND booking_date <= :e"
            ),
            {**params, **period, "c": EPARGNE_3A},
        ).scalar_one()
    )
    at_viac = int(
        conn.execute(
            text(
                "SELECT coalesce(sum(amount_minor), 0) FROM entries "
                f"WHERE ({PENSION_DEPOSITS}) AND currency = :ccy "
                "AND booking_date >= :s AND booking_date <= :e"
            ),
            period,
        ).scalar_one()
    )
    paid = max(from_bank, at_viac)
    return {
        "year": year,
        "cap": in_base(cap),
        "paid": in_base(paid),
        "margin": in_base(max(0, cap - paid)),
        "source": "viac" if at_viac and at_viac >= from_bank else "bank",
    }


# --- routes -----------------------------------------------------------------------------------


# --- export -----------------------------------------------------------------------------------
