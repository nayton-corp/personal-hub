"""Charges fixes : quand elles ont été payées, et vers quand on les attend (audit du 10/11, B2).

Une charge fixe n'avance pas au rythme du mois : elle est due en entier, un jour donné. L'écran
dit donc « Payé le 1 nov. » ou « Attendu vers le 15 nov. », pas une barre. Le jour attendu est
tiré de l'habitude : le dernier débit de la catégorie dans chacun des mois d'avant, compté en
jours depuis le début du mois budgétaire, puis le jour médian. Des dates seulement, par
catégorie : aucun montant, aucune écriture.
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import Connection, text

from hub.domains.finance.classement.app.totals import _scope
from hub.domains.finance.registre.model import period as period_rules
from hub.domains.finance.registre.model.amounts import previous_months

HABIT_MONTHS = 3  # mois regardés pour connaître le jour habituel
_LAST = (
    "SELECT v.category_id, max(v.booking_date) "
    "FROM v_entry_allocation v JOIN entries e ON e.seq = v.entry_seq "
    "JOIN accounts a ON a.id = v.account_id "
    "JOIN categories c ON c.id = v.category_id "
    "WHERE {scope} AND e.kind != 'opening' AND c.grp = 'fixed' AND v.amount_minor < 0 "
    "AND v.booking_date >= :s AND v.booking_date < :e GROUP BY 1"
)


def last_paid(conn: Connection, start: date, end: date) -> dict[str, str]:
    """Catégorie fixe → date de son dernier débit entre `start` inclus et `end` exclu."""
    scope, params = _scope(conn)
    rows = conn.execute(
        text(_LAST.format(scope=scope)), {**params, "s": start.isoformat(), "e": end.isoformat()}
    )
    return {str(r[0]): str(r[1]) for r in rows}


def expected(conn: Connection, month: str) -> dict[str, str]:
    """Catégorie fixe → date où on l'attend dans le mois budgétaire `month`, d'après les mois
    d'avant ; absente sans habitude connue."""
    offsets: dict[str, list[int]] = {}
    for m in previous_months(month, HABIT_MONTHS):
        start, end = period_rules.bounds(m)
        for cat, on in last_paid(conn, start, end).items():
            offsets.setdefault(cat, []).append((date.fromisoformat(on) - start).days)
    start, end = period_rules.bounds(month)
    out: dict[str, str] = {}
    for cat, found in offsets.items():
        usual = sorted(found)[len(found) // 2]
        out[cat] = min(start + timedelta(days=usual), end - timedelta(days=1)).isoformat()
    return out
