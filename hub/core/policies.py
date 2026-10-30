"""Paliers d'approbation (Double Sas) : `human` (une carte), `auto_digest` (appliqué, repris au
résumé du jour avec son inverse), `auto` (appliqué sans rien dire).

Le domaine déclare le palier par défaut de chaque type (`ProposalKind.tier`, `human` sauf
mention) ; la personne le change par `hub proposals policy` (`approval_policies`). Un jeton (un
modèle) reste au palier `human` tant qu'il ne déclare pas `external_text = False` : une
proposition tirée d'un texte externe passe toujours par une carte.
"""

from __future__ import annotations

from typing import get_args

from sqlalchemy import Connection, text

from hub.core.auth import Principal
from hub.core.domain import Tier

TIERS: tuple[str, ...] = get_args(Tier)


def tier(conn: Connection, domain: str, kind: str, default: str = "human") -> str:
    row = conn.execute(
        text("SELECT tier FROM approval_policies WHERE domain = :d AND kind = :k"),
        {"d": domain, "k": kind},
    ).first()
    return str(row[0]) if row is not None else default


def tier_for(
    conn: Connection,
    principal: Principal,
    domain: str,
    kind: str,
    default: str,
    external_text: bool | None,
) -> str:
    if not principal.is_app and external_text is not False:
        return "human"
    return tier(conn, domain, kind, default)


def overrides(conn: Connection) -> dict[tuple[str, str], str]:
    rows = conn.execute(text("SELECT domain, kind, tier FROM approval_policies")).fetchall()
    return {(r[0], r[1]): r[2] for r in rows}


def set_tier(conn: Connection, domain: str, kind: str, value: str | None) -> None:
    """`None` rend au type son palier par défaut."""
    if value is not None and value not in TIERS:
        raise ValueError(f"palier inconnu : {value} ({', '.join(TIERS)})")
    conn.execute(
        text("DELETE FROM approval_policies WHERE domain = :d AND kind = :k"),
        {"d": domain, "k": kind},
    )
    if value is not None:
        conn.execute(
            text("INSERT INTO approval_policies (domain, kind, tier) VALUES (:d, :k, :t)"),
            {"d": domain, "k": kind, "t": value},
        )
