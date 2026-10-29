"""Écriture au registre et vérification de la chaîne (tickets L1-01 et L1-02).

Toute ligne d'une table protégée passe par `append()`, appelé dans une transaction
`BEGIN IMMEDIATE` (`hub.platform.db.begin_immediate`) : la tête du journal lue ici ne peut plus
changer avant le COMMIT.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import Connection, text

from hub.domains.finance import hashing
from hub.kernel import canonical
from hub.kernel.clock import now_iso
from hub.kernel.text import normalize

DEDUP_VERSION = "v1"


class LedgerError(RuntimeError):
    pass


def _head(conn: Connection) -> tuple[str, int]:
    row = conn.execute(
        text("SELECT chain_hash, epoch FROM journal ORDER BY seq DESC LIMIT 1")
    ).first()
    if row:
        return row[0], row[1]
    # base reconstruite par rejeu : son journal ouvre l'époque inscrite dans `rebuild_meta`
    # (journal vide seulement ; la table n'existe qu'à partir de 0005)
    epoch = None
    if conn.execute(
        text("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'rebuild_meta'")
    ).first():
        epoch = conn.execute(
            text("SELECT epoch FROM rebuild_meta WHERE id = 1")
        ).scalar_one_or_none()
    return hashing.GENESIS, int(epoch) if epoch is not None else 1


def append(conn: Connection, table: str, values: Mapping[str, Any]) -> int:
    """Ajoute une ligne et son maillon de journal ; renvoie le rowid (le `seq`)."""
    if table not in hashing.FIELDS:
        raise LedgerError(f"table non protégée : {table}")
    version = hashing.current_version(table)
    missing = [f for f in hashing.FIELDS[table][version] if f not in values]
    if missing:
        raise LedgerError(f"{table} : champs absents {missing}")
    row = {**values, "hash_v": version}
    digest = hashing.row_hash(table, row, version)
    if table == "entries":
        row["row_hash"] = digest
    cols = ", ".join(row)
    marks = ", ".join(f":{c}" for c in row)
    row_seq = int(
        conn.execute(
            text(f"INSERT INTO {table} ({cols}) VALUES ({marks}) RETURNING rowid"),
            row,
        ).scalar_one()
    )
    prev, epoch = _head(conn)
    conn.execute(
        text(
            "INSERT INTO journal (tbl, row_seq, row_hash, epoch, prev_hash, chain_hash) "
            "VALUES (:t, :s, :h, :e, :p, :c)"
        ),
        {
            "t": table,
            "s": row_seq,
            "h": digest,
            "e": epoch,
            "p": prev,
            "c": hashing.chain_hash(prev, table, row_seq, digest),
        },
    )
    return row_seq


def entry_id(dedup_key: str) -> str:
    """Identifiant déterministe : les décisions citent l'écriture par lui, jamais par `seq`."""
    return f"e{dedup_key[:31]}"


def dedup_hash(base: str) -> str:
    return hashlib.sha256(f"{DEDUP_VERSION}|{base}".encode()).hexdigest()


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


def append_event(
    conn: Connection, type_: str, urn: str, payload: Mapping[str, Any] | None = None
) -> int:
    return append(
        conn,
        "events",
        {
            "type": type_,
            "urn": urn,
            "payload_json": canonical.dumps(dict(payload or {})),
            "created_at": now_iso(),
        },
    )


@dataclass
class VerifyResult:
    ok: bool
    links: int = 0
    rows: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)  # tables et numéros de ligne seulement

    def public(self) -> dict[str, Any]:
        return {"ok": self.ok, "links": self.links, "rows": self.rows, "errors": self.errors[:20]}


def verify(conn: Connection) -> VerifyResult:
    """Chaîne du journal, puis empreinte de chaque ligne selon sa version, puis complétude."""
    result = VerifyResult(ok=True)
    rows: dict[str, dict[int, Mapping[str, Any]]] = {}
    for table in hashing.PROTECTED:
        found = conn.execute(text(f"SELECT rowid AS _rowid, * FROM {table}")).mappings()
        rows[table] = {int(r["_rowid"]): dict(r) for r in found}
        result.rows[table] = len(rows[table])

    prev = hashing.GENESIS
    seen: Counter[str] = Counter()
    for link in conn.execute(
        text("SELECT seq, tbl, row_seq, row_hash, prev_hash, chain_hash FROM journal ORDER BY seq")
    ):
        result.links += 1
        where = f"journal {link.seq} ({link.tbl} {link.row_seq})"
        if link.prev_hash != prev:
            result.errors.append(f"{where} : maillon précédent différent")
        if hashing.chain_hash(link.prev_hash, link.tbl, link.row_seq, link.row_hash) != (
            link.chain_hash
        ):
            result.errors.append(f"{where} : maillon altéré")
        prev = link.chain_hash
        row = rows.get(link.tbl, {}).get(link.row_seq)
        if row is None:
            result.errors.append(f"{where} : ligne absente")
            continue
        seen[link.tbl] += 1
        try:
            digest = hashing.row_hash(link.tbl, row, int(row["hash_v"]))
        except ValueError:
            result.errors.append(f"{where} : version d'empreinte inconnue")
            continue
        if digest != link.row_hash or (link.tbl == "entries" and row["row_hash"] != digest):
            result.errors.append(f"{where} : ligne altérée")
    for table, count in result.rows.items():
        if seen[table] != count:
            result.errors.append(f"{table} : {count - seen[table]} ligne(s) hors journal")
    result.ok = not result.errors
    return result
