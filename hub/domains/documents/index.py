"""L'index local : les passages des documents, cherchés par FTS5 (trigrammes, insensible à la
casse, un code d'appareil « WM14N2 » se trouve tel quel). Recalculable depuis l'archive."""

from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy import Connection, text

from hub.domains.documents import text as reader
from hub.domains.documents.model import chunk

TERM = re.compile(r"\w{3,}")
SEARCH = """
SELECT p.document_id, p.page, p.text, bm25(passages_fts) AS rank
FROM passages_fts JOIN passages p ON p.seq = passages_fts.rowid
WHERE passages_fts MATCH :q
  AND (:all OR p.document_id IN (SELECT value FROM json_each(:ids)))
ORDER BY rank LIMIT :n
"""


def write(conn: Connection, document_id: str, name: str, data: bytes) -> int:
    """(Ré)écrit les passages d'un document ; rend leur nombre."""
    conn.execute(text("DELETE FROM passages WHERE document_id = :d"), {"d": document_id})
    try:
        found = reader.pages(name, data)
    except reader.TextError:
        found = []
    passages = [(page, c) for page, body in found for c in chunk(body)]
    for page, body in passages:
        conn.execute(
            text("INSERT INTO passages (document_id, page, text) VALUES (:d, :p, :t)"),
            {"d": document_id, "p": page, "t": body},
        )
    return len(passages)


def indexed(conn: Connection) -> set[str]:
    return {r[0] for r in conn.execute(text("SELECT DISTINCT document_id FROM passages"))}


def query(q: str) -> str | None:
    """Une question en requête FTS5 : chaque mot de 3 lettres ou plus, entre guillemets, en OU."""
    terms = sorted({t.casefold() for t in TERM.findall(q)})
    return " OR ".join(f'"{t}"' for t in terms) or None


def search(conn: Connection, q: str, limit: int, allowed: set[str] | None) -> list[dict[str, Any]]:
    """Les meilleurs passages ; `allowed` restreint aux documents permis (None : tous)."""
    match = query(q)
    if match is None or allowed == set():
        return []
    ids = json.dumps(sorted(allowed or ()))
    found = conn.execute(
        text(SEARCH), {"q": match, "n": limit, "all": allowed is None, "ids": ids}
    ).all()
    return [{"document_id": d, "page": p, "text": t, "rank": r} for d, p, t, r in found]
