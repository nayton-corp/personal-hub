"""documents.db : écrire par le registre chaîné, lire l'état courant.

La fiche courante est sa dernière version ; la marque « foyer » d'un document est sa dernière
marque (aucune : privé). Les passages, eux, ne sont pas protégés : ils se recalculent.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import Connection, text

from hub.core import integrity
from hub.kernel import canonical
from hub.kernel.clock import now_iso

FIELDS: dict[str, tuple[str, ...]] = {
    "cards": ("card_id", "fields_json", "at"),
    "documents": ("id", "title", "file_name", "sha256", "mime", "card_id", "at"),
    "marks": ("document_id", "household", "at"),
}
LEDGER = integrity.Ledger({**integrity.COMMON_FIELDS, **{t: {1: f} for t, f in FIELDS.items()}})


def append(conn: Connection, table: str, row: dict[str, Any]) -> int:
    return LEDGER.append(conn, table, {f: row.get(f) for f in FIELDS[table]})


def add_card_version(conn: Connection, card_id: str, fields: dict[str, Any]) -> int:
    row = {"card_id": card_id, "fields_json": canonical.dumps(fields), "at": now_iso()}
    return append(conn, "cards", row)


def add_document(conn: Connection, row: dict[str, Any]) -> int:
    return append(conn, "documents", {**row, "at": row.get("at") or now_iso()})


def add_mark(conn: Connection, document_id: str, household: bool) -> int:
    row = {"document_id": document_id, "household": int(household), "at": now_iso()}
    return append(conn, "marks", row)


def rows(conn: Connection, table: str, after: int = 0) -> list[tuple[int, dict[str, Any]]]:
    """Les lignes protégées d'une table, telles qu'archivées (sans `hash_v`)."""
    cols = ", ".join(FIELDS[table])
    found = conn.execute(
        text(f"SELECT seq, {cols} FROM {table} WHERE seq > :a ORDER BY seq"),  # noqa: S608
        {"a": after},
    ).all()
    return [(r[0], dict(zip(FIELDS[table], r[1:], strict=True))) for r in found]


def cards(conn: Connection) -> dict[str, dict[str, Any]]:
    found = conn.execute(
        text(
            "SELECT card_id, fields_json FROM cards WHERE seq IN "
            "(SELECT max(seq) FROM cards GROUP BY card_id) ORDER BY card_id"
        )
    ).all()
    return {r[0]: json.loads(r[1]) for r in found}


def card(conn: Connection, card_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        text("SELECT fields_json FROM cards WHERE card_id = :c ORDER BY seq DESC LIMIT 1"),
        {"c": card_id},
    ).first()
    return json.loads(row[0]) if row else None


DOCUMENTS = """
SELECT d.id, d.title, d.file_name, d.sha256, d.mime, d.card_id, d.at,
       coalesce((SELECT m.household FROM marks m WHERE m.document_id = d.id
                 ORDER BY m.seq DESC LIMIT 1), 0) AS household
FROM documents d
"""
DOC_COLS = ("id", "title", "file_name", "sha256", "mime", "card_id", "at", "household")


def documents(
    conn: Connection, *, household_only: bool = False, card_id: str | None = None
) -> list[dict[str, Any]]:
    found = conn.execute(
        text(f"SELECT * FROM ({DOCUMENTS}) WHERE (:c IS NULL OR card_id = :c) ORDER BY at DESC"),  # noqa: S608
        {"c": card_id},
    ).all()
    out = [dict(zip(DOC_COLS, r, strict=True)) for r in found]
    for d in out:
        d["household"] = bool(d["household"])
    return [d for d in out if d["household"] or not household_only]


def document(conn: Connection, document_id: str) -> dict[str, Any] | None:
    found = [d for d in documents(conn) if d["id"] == document_id]
    return found[0] if found else None


def by_sha(conn: Connection, sha256: str) -> str | None:
    row = conn.execute(
        text("SELECT id FROM documents WHERE sha256 = :s ORDER BY seq LIMIT 1"), {"s": sha256}
    ).first()
    return str(row[0]) if row else None
