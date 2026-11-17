"""Détail d'un import de relevé (lecture du registre) : statut, relevés reconnus, doublons."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import Connection, text


def import_detail(conn: Connection, import_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        text(
            "SELECT id, source, file_name, received_at, status, stats_json FROM imports "
            "WHERE id = :i"
        ),
        {"i": import_id},
    ).first()
    if row is None:
        return None
    statements = [
        {
            "index": s[0],
            "account_id": s[1],
            "opbd_date": s[2],
            "clbd_date": s[3],
            "status": s[4],
            "reasons": json.loads(s[5]),
            "new": s[6],
            "duplicates": s[7],
        }
        for s in conn.execute(
            text(
                "SELECT stmt_index, account_id, opbd_date, clbd_date, status, reasons_json, "
                "new_entries, duplicates FROM import_statements WHERE import_id = :i "
                "ORDER BY stmt_index"
            ),
            {"i": import_id},
        )
    ]
    return {
        "id": row[0],
        "source": row[1],
        "file_name": row[2],
        "received_at": row[3],
        "status": row[4],
        "stats": json.loads(row[5]),
        "statements": statements,
        "proposal_id": None,  # carte apply_import : ajoutée par la route (core.db)
    }
