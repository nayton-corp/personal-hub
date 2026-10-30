"""Ce qu'un autre domaine peut lire de la finance (chantier S6) : des agrégats seulement, jamais
une écriture. Le contrat d'indépendance des domaines ne laisse passer que ce module ; l'appelant
fournit une connexion en lecture à `finance.db`.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Connection

from hub.domains.finance.classement.app import totals
from hub.domains.finance.patrimoine.app import valuation


def month_totals(conn: Connection, month: str) -> dict[str, Any]:
    """Revenus, dépenses et montant par catégorie d'un mois, comme pour la portée
    `finance:aggregates` (une catégorie de moins de 3 écritures est fondue dans « Autres »)."""
    return totals.summary(conn, month, aggregates_only=True)


def net_worth(conn: Connection, on_date: str) -> dict[str, Any]:
    """Patrimoine net à une date, dans la devise de base, en centimes, et par enveloppe."""
    v = valuation.value_at(conn, on_date)
    return {
        "on_date": v.on_date,
        "net_worth": v.net_worth,
        "liquid": v.liquid,
        "by_envelope": dict(v.by_envelope),
        "complete": not (v.missing_fx or v.missing_prices),
    }
