"""Empreintes versionnées des tables protégées et chaîne du journal (revue d'architecture).

Une ligne se vérifie toujours avec la liste de champs de sa version (`hash_v`). Ajouter une
colonne crée la version suivante ; une version existante ne change jamais.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

from hub.core import canonical

GENESIS = "0" * 64

# champs du JSON canonique, par table puis par version
FIELDS: dict[str, dict[int, tuple[str, ...]]] = {
    "entries": {
        1: (
            "id",
            "account_id",
            "kind",
            "booking_date",
            "value_date",
            "amount_minor",
            "currency",
            "counterparty",
            "counterparty_iban",
            "label",
            "remittance",
            "bank_ref",
            "bank_tx_code",
            "fx_json",
            "dedup_key",
            "corrects_seq",
            "import_id",
            "proposal_id",
            "created_at",
        )
    },
    "categorizations": {
        1: ("entry_seq", "category_id", "source", "rule_id", "proposal_id", "created_at")
    },
    "categorization_lines": {1: ("categorization_seq", "line", "category_id", "amount_minor")},
    "notes": {1: ("entry_seq", "text", "proposal_id", "created_at")},
    "checkpoints": {1: ("account_id", "on_date", "kind", "amount_minor", "import_id")},
    "budgets": {
        1: ("category_id", "monthly_minor", "currency", "valid_from", "proposal_id", "created_at")
    },
    "tags": {1: ("id", "name", "kind", "created_at")},
    "taggings": {1: ("entry_seq", "tag_id", "active", "proposal_id", "created_at")},
    "applied_proposals": {1: ("proposal_id", "kind", "result_json", "applied_at")},
    "events": {1: ("type", "urn", "payload_json", "created_at")},
}

# colonnes volontairement hors empreinte : identité de ligne, dérivés recalculables, empreinte
NOT_HASHED: dict[str, frozenset[str]] = {
    "entries": frozenset({"seq", "search_text", "hash_v", "row_hash"}),
    "notes": frozenset({"seq", "search_text", "hash_v"}),
}
DEFAULT_NOT_HASHED = frozenset({"seq", "hash_v"})

PROTECTED = tuple(FIELDS)


def current_version(table: str) -> int:
    return max(FIELDS[table])


def not_hashed(table: str) -> frozenset[str]:
    return NOT_HASHED.get(table, DEFAULT_NOT_HASHED)


def row_hash(table: str, row: Mapping[str, Any], version: int | None = None) -> str:
    v = current_version(table) if version is None else version
    try:
        fields = FIELDS[table][v]
    except KeyError:
        raise ValueError(f"version d'empreinte inconnue : {table} v{v}") from None
    return canonical.sha256_hex({f: row[f] for f in fields})


def chain_hash(prev_hash: str, table: str, row_seq: int, row_digest: str) -> str:
    return hashlib.sha256(f"{prev_hash}|{table}|{row_seq}|{row_digest}".encode()).hexdigest()
