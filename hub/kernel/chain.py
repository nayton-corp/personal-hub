"""Empreintes versionnées et maillons d'une chaîne d'ajout seul (chantier S3), sans base.

Une ligne se hache avec la liste de champs de sa version, en JSON canonique ; une version
existante ne change jamais (une colonne en plus crée la suivante). Chaque maillon du journal
scelle le précédent : sha256(prev|table|seq|empreinte).
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

from hub.kernel import canonical

GENESIS = "0" * 64

# table → version → champs hachés, déclaré par chaque domaine
Fields = Mapping[str, Mapping[int, tuple[str, ...]]]


def current_version(fields: Fields, table: str) -> int:
    return max(fields[table])


def row_hash(fields: Fields, table: str, row: Mapping[str, Any], version: int | None = None) -> str:
    v = current_version(fields, table) if version is None else version
    try:
        names = fields[table][v]
    except KeyError:
        raise ValueError(f"version d'empreinte inconnue : {table} v{v}") from None
    return canonical.sha256_hex({f: row[f] for f in names})


def chain_hash(prev_hash: str, table: str, row_seq: int, row_digest: str) -> str:
    return hashlib.sha256(f"{prev_hash}|{table}|{row_seq}|{row_digest}".encode()).hexdigest()
