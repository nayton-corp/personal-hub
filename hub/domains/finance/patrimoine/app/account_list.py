"""Comptes de l'app (ticket L1-10) : chaque compte avec son solde au registre, sa valeur dans la
devise de base, son but et sa disponibilité (déduits du type de compte s'ils ne sont pas réglés)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Connection, text

from hub.domains.finance.patrimoine.app import valuation
from hub.domains.finance.registre.app.reads import last_clbd
from hub.domains.finance.registre.model.amounts import (
    money,
)
from hub.kernel.text import mask_iban

GOALS = ("current", "safety", "projects", "long_term", "retirement")


def availability(kind: str, liquid: bool) -> str:
    """Délai pour disposer de l'argent : tout de suite, quelques jours (vente, retrait),
    ou bloqué (prévoyance)."""
    if liquid:
        return "immediate"
    return "locked" if kind == "pension" else "days"


def default_goal(kind: str, budget_account: bool) -> str:
    """Objectif d'un compte qui n'en a pas reçu : déduit de son type."""
    if kind == "pension":
        return "retirement"
    if kind in ("securities", "crypto"):
        return "long_term"
    return "current" if budget_account else "safety"


def accounts(conn: Connection) -> list[dict[str, Any]]:
    out = []
    rows = conn.execute(
        text(
            "SELECT a.id, a.institution, a.name, a.kind, a.currency, a.iban, a.liquid, "
            "a.budget_account, coalesce(b.balance_minor, 0), b.last_booking, a.external_ref, "
            "a.goal, a.availability, a.category, a.hidden, a.target_minor "
            "FROM accounts a LEFT JOIN v_balances b ON b.account_id = a.id "
            "ORDER BY a.institution, a.name"
        )
    ).fetchall()
    positions = valuation.Positions(conn)
    # « tout débit de ce compte → … » : la règle sans motif d'un compte, la plus prioritaire
    spend = {}
    for acc, rid, cat in conn.execute(
        text(
            "SELECT account_id, id, category_id FROM rules WHERE account_id IS NOT NULL "
            "AND active = 1 AND trim(pattern) = '' AND direction = 'debit' "
            "ORDER BY priority DESC, id DESC"
        )
    ):
        spend[acc] = {"rule_id": rid, "category_id": cat}
    for r in rows:
        clbd = last_clbd(conn, r[0])
        value, missing = valuation.account_value(positions, r[0], int(r[8]), "9999-12-31")
        out.append(
            {
                "id": r[0],
                "institution": r[1],
                "name": r[2],
                "kind": r[3],
                "iban": mask_iban(r[5]),
                "external_ref": r[10],
                "liquid": bool(r[6]),
                "budget_account": bool(r[7]),
                "availability": r[12] or availability(r[3], bool(r[6])),
                "availability_set": r[12] is not None,
                "availability_auto": availability(r[3], bool(r[6])),
                "goal": r[11] or default_goal(r[3], bool(r[7])),
                "goal_set": r[11] is not None,
                # catégorie imposée à toutes les lignes du compte ; NULL : déduite de chaque ligne
                "category": r[13],
                "hidden": bool(r[14]),
                # montant visé, dans la devise du compte ; None sans montant
                "target": money(r[15], r[4]) if r[15] is not None else None,
                "spend_rule": spend.get(r[0]),
                "balance": money(r[8], r[4]),
                # valeur de marché pour un compte de titres (parts × dernier cours), sinon le solde
                "value": money(value, r[4]),
                "missing_prices": missing,
                "last_booking": r[9],
                "last_clbd": clbd,
            }
        )
    return out
