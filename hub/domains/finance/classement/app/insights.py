"""Chiffres de l'app (ticket L2-02) : les neuf calculs du dashboard prototype, côté serveur et
en centimes.

Le « mois en cours » vient toujours du paramètre `month` et « aujourd'hui » de l'appelant ;
rien n'est déduit des données. Le début d'année est le 31 décembre précédent. Les rapports
sont des décimales en texte (`"0.2534"`), jamais des flottants.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from sqlalchemy import Connection, text

from hub.domains.finance import thresholds
from hub.domains.finance.classement.app.totals import Line, Lines, Totals, period_report
from hub.domains.finance.packs import CountryPack
from hub.domains.finance.registre.app.reads import budget_accounts, in_list, last_dates
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

PENSION_DEPOSITS = institutions.like_any(
    "bank_tx_code", institutions.prefixes(pension_deposit=True)
)
EXPENSE_GROUPS = ("fixed", "variable")
FLOW_GROUPS = ("fixed", "variable", "savings")
NAMES_EXTRA = {UNCATEGORIZED: "À catégoriser", OTHERS: "Autres"}


# --- périodes ---------------------------------------------------------------------------------


# --- briques ----------------------------------------------------------------------------------


def category_names(conn: Connection) -> dict[str, str]:
    names = {r[0]: r[1] for r in conn.execute(text("SELECT id, name FROM categories"))}
    return {**names, **NAMES_EXTRA}


@dataclass(frozen=True)
class Target:
    """La cible d'une catégorie telle que saisie, avec sa cadence (audit M4)."""

    amount: int
    cadence: str  # month | year

    @property
    def monthly(self) -> int:
        """La cible du mois ; d'une cible annuelle, un douzième (lecture seulement)."""
        return self.amount if self.cadence == "month" else (self.amount + 6) // 12

    @property
    def annual(self) -> int:
        return self.amount if self.cadence == "year" else self.amount * 12


def target_of(monthly: int, amount: int | None, cadence: str | None, fallback: str) -> Target:
    """Une ligne de `budgets` : le montant saisi s'il est là, sinon l'ancien mensuel relu avec la
    cadence du réglage (`budget_cadence`)."""
    if amount is not None and cadence is not None:
        return Target(int(amount), cadence)
    cadence = fallback or "month"
    return Target(int(monthly) * 12 if cadence == "year" else int(monthly), cadence)


_TARGETS = (
    "SELECT b.category_id, b.monthly_minor, b.amount_minor, b.cadence, c.cadence FROM budgets b "
    "LEFT JOIN budget_cadence c ON c.category_id = b.category_id "
    "WHERE b.currency = :ccy AND b.seq = (SELECT max(seq) FROM budgets "
    "WHERE category_id = b.category_id{where})"
)


def targets(conn: Connection, month: str) -> dict[str, Target]:
    """Cible en vigueur au début du mois, par catégorie (la dernière ligne gagne). Une dernière
    ligne à zéro retire la cible : la catégorie redevient « hors budget », elle n'est pas
    « dépassée » au premier centime (audit du 10/11, B3)."""
    rows = conn.execute(
        text(_TARGETS.format(where=" AND valid_from <= :m")),
        {"m": f"{month}-01", "ccy": base_currency()},
    )
    found = {r[0]: target_of(r[1], r[2], r[3], r[4]) for r in rows}
    return {c: t for c, t in found.items() if t.amount > 0}


def category_groups(conn: Connection) -> dict[str, str]:
    return {r[0]: r[1] for r in conn.execute(text("SELECT id, grp FROM categories"))}


def yearly(conn: Connection) -> frozenset[str]:
    """Catégories suivies à l'année (vacances, entretien) : la cadence de leur dernière cible,
    sinon le réglage `budget_cadence` ; elles sortent du budget et du reste à vivre du mois."""
    rows = conn.execute(text(_TARGETS.format(where="")), {"ccy": base_currency()}).fetchall()
    found = {str(r[0]) for r in rows if target_of(r[1], r[2], r[3], r[4]).cadence == "year"}
    known = {str(r[0]) for r in rows}
    settings = conn.execute(text("SELECT category_id FROM budget_cadence WHERE cadence = 'year'"))
    return frozenset(found | {str(r[0]) for r in settings if str(r[0]) not in known})


def expense_budget(conn: Connection, month: str) -> int | None:
    groups, year = category_groups(conn), yearly(conn)
    found = {
        c: t.monthly
        for c, t in targets(conn, month).items()
        if groups.get(c) in EXPENSE_GROUPS and c not in year
    }
    return sum(found.values()) if found else None


def monthly_expenses(lines: list[Line], year: frozenset[str]) -> int:
    """Dépenses de la période hors catégories suivies à l'année, en positif."""
    return -sum(x.minor for x in lines if x.group in EXPENSE_GROUPS and x.category not in year)


def report_for(conn: Connection, months: list[str]) -> Lines:
    start, end = span(months)
    return period_report(conn, start, end)


def lines_for(conn: Connection, months: list[str]) -> list[Line]:
    return report_for(conn, months).lines


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


def stale_accounts(conn: Connection, today: date, days: int | None = None) -> int:
    """Comptes affichés dont la dernière donnée (écriture, position, solde de clôture) a plus de
    `days` jours (réglage `stale_account_days`). Un compte jamais alimenté n'en fait pas partie."""
    limit = (today - timedelta(days=days or thresholds.current().stale_account_days)).isoformat()
    ids = conn.execute(
        text("SELECT id FROM accounts WHERE closed_on IS NULL AND hidden = 0")
    ).scalars()
    dates = last_dates(conn)
    return sum(1 for a in ids if (d := dates.get(a)) is not None and d < limit)


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
    conn: Connection, year: int, until: date, cap: int | None, pack: CountryPack
) -> dict[str, Any]:
    """Versements de l'épargne-retraite plafonnée (pilier 3a) de l'année : ceux que la
    fondation a reçus (avis de versement) ou, à défaut, les paiements catégorisés dans la
    catégorie du pack sur les comptes courants ; le plus grand des deux, pour qu'un historique
    incomplet ou une catégorie manquante ne sous-estime rien. `cap` : `[finance]
    pillar3a_cap_minor`, sinon le plafond du pack (une année absente prend le dernier connu)."""
    if cap is None:
        cap = pack.pension_cap(year) or 0
    period = {"ccy": base_currency(), "s": f"{year}-01-01", "e": until.isoformat()}
    ids, params = in_list("a", budget_accounts(conn))
    from_bank = 0
    if pack.pension_category:
        from_bank = -int(
            conn.execute(
                text(
                    "SELECT coalesce(sum(amount_minor), 0) FROM v_entry_allocation "
                    f"WHERE category_id = :c AND account_id IN {ids} AND currency = :ccy "
                    "AND booking_date >= :s AND booking_date <= :e"
                ),
                {**params, **period, "c": pack.pension_category},
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
