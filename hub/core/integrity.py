"""Intégrité d'un domaine, fournie par le cœur (chantier S3) : tables en ajout seul, empreinte
versionnée de chaque ligne, journal chaîné, `applied_proposals` et `events`.

Un domaine déclare ses champs hachés (`hub.kernel.chain.Fields`) et crée ses tables avec les
aides de migration ci-dessous ; `Ledger.append` écrit une ligne et son maillon dans la même
transaction (`BEGIN IMMEDIATE` : la tête lue ne peut plus changer avant le COMMIT) et
`Ledger.verify` rejoue tout : maillons, empreintes, lignes hors journal.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import Connection, text

from hub.core.domain import Event
from hub.kernel import canonical, chain
from hub.kernel.clock import now_iso
from hub.kernel.ids import urn

# --- aides de migration -------------------------------------------------------------------------

JOURNAL = """
CREATE TABLE journal (
  seq        INTEGER PRIMARY KEY,
  tbl        TEXT NOT NULL,
  row_seq    INTEGER NOT NULL,                   -- rowid de la ligne
  row_hash   TEXT NOT NULL,                      -- selon le hash_v de la ligne
  epoch      INTEGER NOT NULL DEFAULT 1,         -- +1 à chaque reconstruction par rejeu
  prev_hash  TEXT NOT NULL,                      -- '0'*64 au début
  chain_hash TEXT NOT NULL,                      -- sha256(prev_hash|tbl|row_seq|row_hash)
  UNIQUE (tbl, row_seq)
)
"""
APPLIED = """
CREATE TABLE applied_proposals (                 -- fait foi : écrite avec l'effet
  proposal_id TEXT PRIMARY KEY,
  kind        TEXT NOT NULL,
  result_json TEXT NOT NULL,
  applied_at  TEXT NOT NULL,
  hash_v      INTEGER NOT NULL
)
"""
EVENTS = """
CREATE TABLE events (                            -- boîte de sortie, lue par curseur
  seq          INTEGER PRIMARY KEY,
  type         TEXT NOT NULL,
  urn          TEXT NOT NULL,
  payload_json TEXT NOT NULL DEFAULT '{}',       -- identifiants et compteurs seulement
  created_at   TEXT NOT NULL,
  hash_v       INTEGER NOT NULL
)
"""
# champs hachés des deux tables communes, version 1 (à reprendre dans les `Fields` du domaine)
COMMON_FIELDS: dict[str, dict[int, tuple[str, ...]]] = {
    "applied_proposals": {1: ("proposal_id", "kind", "result_json", "applied_at")},
    "events": {1: ("type", "urn", "payload_json", "created_at")},
}


def append_only(table: str, code: str = "ledger.append_only") -> list[str]:
    """Deux triggers qui refusent UPDATE et DELETE (`hub verify` les contrôle, S2)."""
    return [
        f"CREATE TRIGGER {table}_no_update BEFORE UPDATE ON {table} "
        f"BEGIN SELECT RAISE(ABORT, '{code}'); END",
        f"CREATE TRIGGER {table}_no_delete BEFORE DELETE ON {table} "
        f"BEGIN SELECT RAISE(ABORT, '{code}'); END",
    ]


def schema() -> list[str]:
    """Le journal et les deux tables communes, protégées : la première migration d'un domaine."""
    return [JOURNAL, APPLIED, EVENTS, *append_only("applied_proposals"), *append_only("events")]


# --- registre -----------------------------------------------------------------------------------


class LedgerError(RuntimeError):
    pass


@dataclass
class VerifyResult:
    ok: bool
    links: int = 0
    rows: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)  # tables et numéros de ligne seulement

    def public(self) -> dict[str, Any]:
        return {"ok": self.ok, "links": self.links, "rows": self.rows, "errors": self.errors[:20]}


@dataclass(frozen=True)
class Ledger:
    """Les tables protégées d'un domaine. `stored_hash` : tables qui gardent aussi leur
    empreinte dans une colonne `row_hash` ; `epoch` : époque d'un journal encore vide (une base
    reconstruite par rejeu en ouvre une nouvelle)."""

    fields: chain.Fields
    stored_hash: frozenset[str] = frozenset()
    epoch: Callable[[Connection], int] = lambda _conn: 1

    @property
    def tables(self) -> tuple[str, ...]:
        return tuple(self.fields)

    def head(self, conn: Connection) -> tuple[str, int]:
        row = conn.execute(
            text("SELECT chain_hash, epoch FROM journal ORDER BY seq DESC LIMIT 1")
        ).first()
        return (row[0], row[1]) if row else (chain.GENESIS, self.epoch(conn))

    def append(self, conn: Connection, table: str, values: Mapping[str, Any]) -> int:
        """Ajoute une ligne et son maillon de journal ; renvoie le rowid (le `seq`)."""
        if table not in self.fields:
            raise LedgerError(f"table non protégée : {table}")
        version = chain.current_version(self.fields, table)
        missing = [f for f in self.fields[table][version] if f not in values]
        if missing:
            raise LedgerError(f"{table} : champs absents {missing}")
        row = {**values, "hash_v": version}
        digest = chain.row_hash(self.fields, table, row, version)
        if table in self.stored_hash:
            row["row_hash"] = digest
        cols = ", ".join(row)
        marks = ", ".join(f":{c}" for c in row)
        row_seq = int(
            conn.execute(
                text(f"INSERT INTO {table} ({cols}) VALUES ({marks}) RETURNING rowid"),  # noqa: S608
                row,
            ).scalar_one()
        )
        prev, epoch = self.head(conn)
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
                "c": chain.chain_hash(prev, table, row_seq, digest),
            },
        )
        return row_seq

    def verify(self, conn: Connection) -> VerifyResult:
        """Chaîne du journal, puis empreinte de chaque ligne selon sa version, puis complétude."""
        result = VerifyResult(ok=True)
        rows: dict[str, dict[int, Mapping[str, Any]]] = {}
        for table in self.tables:
            found = conn.execute(text(f"SELECT rowid AS _rowid, * FROM {table}")).mappings()  # noqa: S608
            rows[table] = {int(r["_rowid"]): dict(r) for r in found}
            result.rows[table] = len(rows[table])
        prev = chain.GENESIS
        seen: Counter[str] = Counter()
        for link in conn.execute(
            text(
                "SELECT seq, tbl, row_seq, row_hash, prev_hash, chain_hash FROM journal "
                "ORDER BY seq"
            )
        ):
            result.links += 1
            where = f"journal {link.seq} ({link.tbl} {link.row_seq})"
            if link.prev_hash != prev:
                result.errors.append(f"{where} : maillon précédent différent")
            if chain.chain_hash(link.prev_hash, link.tbl, link.row_seq, link.row_hash) != (
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
                digest = chain.row_hash(self.fields, link.tbl, row, int(row["hash_v"]))
            except ValueError:
                result.errors.append(f"{where} : version d'empreinte inconnue")
                continue
            if digest != link.row_hash or (
                link.tbl in self.stored_hash and row["row_hash"] != digest
            ):
                result.errors.append(f"{where} : ligne altérée")
        for table, count in result.rows.items():
            if seen[table] != count:
                result.errors.append(f"{table} : {count - seen[table]} ligne(s) hors journal")
        result.ok = not result.errors
        return result

    # --- les deux tables communes du contrat de domaine ---------------------------------------

    def append_event(
        self, conn: Connection, type_: str, urn: str, payload: Mapping[str, Any] | None = None
    ) -> int:
        return self.append(
            conn,
            "events",
            {
                "type": type_,
                "urn": urn,
                "payload_json": canonical.dumps(dict(payload or {})),
                "created_at": now_iso(),
            },
        )

    def record_applied(
        self, conn: Connection, proposal_id: str, kind: str, result: dict[str, Any]
    ) -> None:
        """`Domain.record_applied` : l'effet et son événement, dans la transaction de l'effet."""
        self.append(
            conn,
            "applied_proposals",
            {
                "proposal_id": proposal_id,
                "kind": kind,
                "result_json": canonical.dumps(result),
                "applied_at": now_iso(),
            },
        )
        self.append_event(
            conn, "proposal.applied", urn("core", "proposal", proposal_id), {"kind": kind}
        )


def applied(conn: Connection, proposal_ids: Sequence[str]) -> dict[str, dict[str, Any]]:
    """`Domain.applied` : ce que `applied_proposals` dit des propositions demandées."""
    if not proposal_ids:
        return {}
    marks = ",".join(f":p{i}" for i in range(len(proposal_ids)))  # marques liées, pas de valeur
    sql = f"SELECT proposal_id, result_json FROM applied_proposals WHERE proposal_id IN ({marks})"  # noqa: S608
    rows = conn.execute(
        text(sql),
        {f"p{i}": p for i, p in enumerate(proposal_ids)},
    ).fetchall()
    return {pid: json.loads(res) for pid, res in rows}


def events_since(conn: Connection, cursor: int, limit: int) -> list[Event]:
    """`Domain.events_since` : la boîte de sortie, après le curseur."""
    rows = conn.execute(
        text(
            "SELECT seq, type, urn, payload_json, created_at FROM events WHERE seq > :c "
            "ORDER BY seq LIMIT :n"
        ),
        {"c": cursor, "n": limit},
    ).fetchall()
    return [Event(r[0], r[1], r[2], json.loads(r[3]), r[4]) for r in rows]
