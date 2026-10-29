"""Écriture au registre et vérification de la chaîne (tickets L1-01 et L1-02).

Toute ligne d'une table protégée passe par `append()`, appelé dans une transaction
`BEGIN IMMEDIATE` (`hub.platform.db.begin_immediate`) : la tête du journal lue ici ne peut plus
changer avant le COMMIT. Le mécanisme (empreinte, maillon, vérification) est celui du cœur
(`hub.core.integrity`, chantier S3) ; la finance y ajoute ses écritures et leurs clés.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Connection, text

from hub.core.integrity import Ledger, LedgerError, VerifyResult
from hub.domains.finance.registre.model import dedup, hashing
from hub.kernel.clock import now_iso
from hub.kernel.text import normalize

__all__ = ["LEDGER", "LedgerError", "VerifyResult", "append", "append_event", "verify"]


def _epoch(conn: Connection) -> int:
    """Base reconstruite par rejeu : son journal vide ouvre l'époque inscrite dans
    `rebuild_meta` (la table n'existe qu'à partir de 0005)."""
    if conn.execute(
        text("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'rebuild_meta'")
    ).first():
        epoch = conn.execute(
            text("SELECT epoch FROM rebuild_meta WHERE id = 1")
        ).scalar_one_or_none()
        if epoch is not None:
            return int(epoch)
    return 1


# le registre de la finance : ses champs hachés, l'empreinte gardée aussi dans entries.row_hash
LEDGER = Ledger(hashing.FIELDS, stored_hash=frozenset({"entries"}), epoch=_epoch)
append = LEDGER.append
append_event = LEDGER.append_event
verify = LEDGER.verify
_head = LEDGER.head


def entry_id(dedup_key: str) -> str:
    """Identifiant déterministe : les décisions citent l'écriture par lui, jamais par `seq`."""
    return f"e{dedup_key[:31]}"


dedup_hash = dedup.dedup_hash  # la clé se calcule sans base (dedup, couche model)


@dataclass(frozen=True)
class NewEntry:
    account_id: str
    booking_date: str
    amount_minor: int
    currency: str
    dedup_key: str
    kind: str = "movement"
    value_date: str | None = None
    counterparty: str | None = None
    counterparty_iban: str | None = None
    label: str = ""
    remittance: str = ""
    bank_ref: str | None = None
    bank_tx_code: str | None = None
    fx_json: str | None = None
    corrects_seq: int | None = None
    import_id: str | None = None
    proposal_id: str | None = None


# noms de remplissage que la banque met à la place d'une contrepartie absente (BCF : cartes,
# TWINT) ; le registre les garde tels quels, ils entrent dans la clé de dédoublonnage
PLACEHOLDER_PARTIES = frozenset({"notprovided", "not provided"})


def party(counterparty: str | None) -> str | None:
    """La contrepartie à montrer, sans les noms de remplissage."""
    if not counterparty or normalize(counterparty) in PLACEHOLDER_PARTIES:
        return None
    return counterparty


def search_text(counterparty: str | None, label: str, remittance: str) -> str:
    return normalize(" ".join(p for p in (counterparty, label, remittance) if p))


def append_entry(conn: Connection, e: NewEntry, created_at: str | None = None) -> tuple[int, str]:
    id_ = entry_id(e.dedup_key)
    seq = append(
        conn,
        "entries",
        {
            "id": id_,
            "account_id": e.account_id,
            "kind": e.kind,
            "booking_date": e.booking_date,
            "value_date": e.value_date,
            "amount_minor": e.amount_minor,
            "currency": e.currency,
            "counterparty": e.counterparty,
            "counterparty_iban": e.counterparty_iban,
            "label": e.label,
            "remittance": e.remittance,
            "bank_ref": e.bank_ref,
            "bank_tx_code": e.bank_tx_code,
            "fx_json": e.fx_json,
            "search_text": search_text(e.counterparty, e.label, e.remittance),
            "dedup_key": e.dedup_key,
            "corrects_seq": e.corrects_seq,
            "import_id": e.import_id,
            "proposal_id": e.proposal_id,
            "created_at": created_at or now_iso(),
        },
    )
    return seq, id_
