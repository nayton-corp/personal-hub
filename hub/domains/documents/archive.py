"""L'archive des documents, chiffrée par age : ce dont la base se reconstruit.

`files/<sha256>.age` garde chaque fichier une fois (le même fichier reçu deux fois n'occupe
qu'une place) ; `records/<table>/<seq>.json.age` garde chaque ligne protégée de la base (une
version de fiche, un document, une marque « foyer »), numérotée comme dans la base. Une ligne
s'archive après sa validation : une ligne annulée n'y entre jamais, une ligne oubliée (arrêt
brutal) est rattrapée par `export`, à chaque écriture et chaque nuit. La clé publique suffit
pour écrire ; relire (reconstruire, indexer) demande la clé de la machine.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from hub.platform import secrets

TABLES = ("cards", "documents", "marks")


class ArchiveError(RuntimeError):
    pass


class Archive:
    def __init__(self, root: Path, key_file: Path) -> None:
        self.root = root
        self.key_file = key_file

    def _recipient(self) -> str:
        if not self.key_file.exists():
            raise ArchiveError("clé age absente : archivage impossible")
        return secrets.recipient(self.key_file)

    def _write(self, target: Path, plain: bytes) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".tmp")
        tmp.write_bytes(secrets.encrypt_for(self._recipient(), plain))
        tmp.replace(target)

    def _read(self, path: Path) -> bytes:
        if not self.key_file.exists():
            raise ArchiveError("clé age absente : relecture impossible")
        return secrets.decrypt_with(self.key_file, path.read_bytes())

    # --- fichiers ---------------------------------------------------------------------------

    def put_file(self, sha256: str, data: bytes) -> None:
        target = self.root / "files" / f"{sha256}.age"
        if not target.exists():
            self._write(target, data)

    def file(self, sha256: str) -> bytes:
        path = self.root / "files" / f"{sha256}.age"
        if not path.exists():
            raise ArchiveError(f"fichier absent de l'archive : {sha256[:12]}")
        return self._read(path)

    # --- lignes -----------------------------------------------------------------------------

    def _record(self, table: str, seq: int) -> Path:
        return self.root / "records" / table / f"{seq:08d}.json.age"

    def has(self, table: str, seq: int) -> bool:
        return self._record(table, seq).exists()

    def put(self, table: str, seq: int, row: dict[str, Any]) -> None:
        if table not in TABLES:
            raise ArchiveError(f"table hors archive : {table}")
        self._write(self._record(table, seq), json.dumps(row, ensure_ascii=False).encode())

    def records(self, table: str) -> Iterator[tuple[int, dict[str, Any]]]:
        """Les lignes d'une table, dans l'ordre de la base."""
        folder = self.root / "records" / table
        if not folder.is_dir():
            return
        for path in sorted(folder.glob("*.json.age")):
            yield int(path.name.split(".", 1)[0]), json.loads(self._read(path))

    def counts(self) -> dict[str, int]:
        return {
            t: len(list((self.root / "records" / t).glob("*.json.age")))
            if (self.root / "records" / t).is_dir()
            else 0
            for t in TABLES
        }
