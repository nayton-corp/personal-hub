"""Les écritures du domaine Documents et sa reconstruction.

Un fichier reçu est archivé (chiffré, une fois par empreinte) avant sa ligne ; une ligne
validée est archivée aussitôt après (`export`). La base se reconstruit donc de l'archive seule :
`rebuild` rejoue les lignes dans l'ordre et réindexe les passages, `compare` vérifie qu'une
reconstruction rend exactement la base vivante.
"""

from __future__ import annotations

import hashlib
import tempfile
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import Connection, Engine

from hub.domains.documents import index, store
from hub.domains.documents import text as reader
from hub.domains.documents.archive import TABLES, Archive
from hub.domains.documents.model import CARD_FIELDS, check_card, merged, plain
from hub.kernel.ids import new_id
from hub.platform.db import begin_immediate

LIBRARY_INBOX = "à-trier"  # dans la bibliothèque de Domia : des photos en attente, pas reprises
Fresh = Callable[[Path], Engine]  # une base neuve et migrée à ce chemin


class Library:
    def __init__(self, engine: Callable[[], Engine], archive: Archive) -> None:
        self._engine = engine
        self.archive = archive

    # --- écritures --------------------------------------------------------------------------

    def add(
        self,
        name: str,
        data: bytes,
        *,
        title: str | None = None,
        card_id: str | None = None,
        household: bool = False,
    ) -> tuple[str, bool]:
        """Archive puis inscrit un document ; le même fichier reçu deux fois n'en fait qu'un.
        Rend (id, ajouté ?)."""
        if len(data) > reader.MAX_BYTES:
            raise ValueError("fichier trop volumineux")
        sha = hashlib.sha256(data).hexdigest()
        with self._engine().connect() as conn:
            known = store.by_sha(conn, sha)
        if known is not None:
            return known, False
        self.archive.put_file(sha, data)
        document_id = new_id("doc_")
        row = {
            "id": document_id,
            "title": (title or Path(name).stem)[:200],
            "file_name": Path(name).name[:200],
            "sha256": sha,
            "mime": reader.mime(name),
            "card_id": card_id,
        }
        with begin_immediate(self._engine()) as conn:
            store.add_document(conn, row)
            if household:
                store.add_mark(conn, document_id, True)
            index.write(conn, document_id, name, data)
        self.export()
        return document_id, True

    def save_card(self, conn: Connection, card_id: str, fields: dict[str, Any]) -> bool:
        """Complète une fiche dans la transaction donnée ; rend faux si rien ne change."""
        check_card(card_id, fields)
        current = store.card(conn, card_id)
        card = merged(current, plain(fields))
        if card == current:
            return False
        store.add_card_version(conn, card_id, card)
        return True

    def export(self) -> int:
        """Archive les lignes validées qui n'y sont pas encore ; rend leur nombre."""
        written = 0
        with self._engine().connect() as conn:
            for table in TABLES:
                for seq, row in store.rows(conn, table):
                    if not self.archive.has(table, seq):
                        self.archive.put(table, seq, row)
                        written += 1
        return written

    # --- arrivées ---------------------------------------------------------------------------

    def process_inbox(self, folder: Path) -> dict[str, int]:
        """Les fichiers de `inbox/documents/` : archivés, inscrits (privés), puis retirés."""
        counts: Counter[str] = Counter()
        if not folder.is_dir():
            return {}
        for path in sorted(folder.iterdir()):
            if not path.is_file() or path.name.startswith("."):
                continue
            if reader.suffix(path.name) not in reader.SUFFIXES:
                counts["ignored"] += 1
                continue
            _, added = self.add(path.name, path.read_bytes())
            counts["added" if added else "duplicates"] += 1
            path.unlink()
        return dict(counts)

    def import_library(self, folder: Path) -> dict[str, int]:
        """Reprise unique de la bibliothèque de Domia : ses fiches YAML, puis ses documents,
        marqués « foyer » (tout le foyer les lisait déjà). Rejouable : rien ne double."""
        counts: Counter[str] = Counter()
        owners: dict[str, str] = {}
        for path in sorted(folder.glob("*.yaml")):
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            fields = {k: v for k, v in data.items() if k in CARD_FIELDS}
            counts["ignored_fields"] += len(data) - len(fields)
            with begin_immediate(self._engine()) as conn:
                counts["cards" if self.save_card(conn, path.stem, fields) else "same"] += 1
            for doc in fields.get("documents") or []:
                owners[str(doc)] = path.stem
        self.export()
        for path in sorted(folder.rglob("*")):
            rel = path.relative_to(folder)
            if not path.is_file() or LIBRARY_INBOX in rel.parts or path.name.startswith("."):
                continue
            if path.suffix == ".yaml" or reader.suffix(path.name) not in reader.SUFFIXES:
                continue
            card = owners.get(str(rel)) or owners.get(path.name)
            if card is None and len(rel.parts) > 1 and (folder / f"{rel.parts[0]}.yaml").exists():
                card = rel.parts[0]  # un dossier au nom de la fiche
            _, added = self.add(path.name, path.read_bytes(), card_id=card, household=True)
            counts["documents" if added else "duplicates"] += 1
        return dict(counts)

    # --- index et reconstruction ------------------------------------------------------------

    def reindex(self, engine: Engine | None = None, *, missing_only: bool = False) -> int:
        engine = engine or self._engine()
        with engine.connect() as conn:
            docs = store.documents(conn)
            done = index.indexed(conn) if missing_only else set()
        written = 0
        for d in docs:
            if d["id"] in done:
                continue
            data = self.archive.file(d["sha256"])
            with begin_immediate(engine) as conn:
                written += index.write(conn, d["id"], d["file_name"], data)
        return written

    def rebuild(self, engine: Engine) -> dict[str, int]:
        """Rejoue l'archive dans une base vide (neuve, ou recréée après une perte), puis
        réindexe ; refuse une base qui a déjà des lignes."""
        with engine.connect() as conn:
            if any(store.rows(conn, t) for t in TABLES):
                raise FileExistsError("la base Documents n'est pas vide")
        counts: dict[str, int] = {}
        with begin_immediate(engine) as conn:
            for table in TABLES:
                counts[table] = 0
                for seq, row in self.archive.records(table):
                    store.LEDGER.append(conn, table, {"seq": seq, **row})
                    counts[table] += 1
        counts["passages"] = self.reindex(engine)
        return counts

    def compare(self, fresh: Fresh) -> dict[str, Any]:
        """Reconstruit dans une base jetable et compare, table par table, à la base vivante."""
        self.export()
        with tempfile.TemporaryDirectory() as tmp:
            other = fresh(Path(tmp) / "documents.db")
            try:
                self.rebuild(other)
                with self._engine().connect() as live, other.connect() as back:
                    tables = {t: (store.rows(live, t), store.rows(back, t)) for t in TABLES}
            finally:
                other.dispose()
        out = {
            t: {"live": len(a), "archive": len(b), "same": a == b} for t, (a, b) in tables.items()
        }
        return {"ok": all(v["same"] for v in out.values()), "tables": out}
