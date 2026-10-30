"""Fichiers reçus (section 4) : empreinte, nom sûr, archives zip dépliées (avec plafonds), et
l'archive chiffrée des originaux."""

from __future__ import annotations

import hashlib
import io
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

from hub.domains.finance.registre.model.errors import ImportRefused
from hub.domains.finance.sources.infra import camt as parser
from hub.platform import secrets

MAX_ZIP_MEMBERS = 500
MAX_ZIP_TOTAL = 200 * 1024 * 1024
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass(frozen=True)
class Incoming:
    name: str
    data: bytes


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_name(name: str) -> str:
    return _SAFE_NAME.sub("_", Path(name).name)[:80] or "fichier"


def expand(name: str, data: bytes) -> list[Incoming]:
    """Un .zip devient un fichier par membre .xml ou .pdf, taille décompressée plafonnée."""
    if not name.lower().endswith(".zip"):
        return [Incoming(name, data)]
    out: list[Incoming] = []
    total = 0
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            members = [i for i in z.infolist() if not i.is_dir()]
            if len(members) > MAX_ZIP_MEMBERS:
                raise ImportRefused("import.invalid_schema", "archive zip : trop de fichiers")
            for info in members:
                if not info.filename.lower().endswith((".xml", ".pdf")):
                    continue
                if info.file_size > parser.MAX_BYTES:
                    raise ImportRefused("import.invalid_schema", "archive zip : fichier trop gros")
                with z.open(info) as fh:
                    member = fh.read(parser.MAX_BYTES + 1)
                if len(member) > parser.MAX_BYTES:
                    raise ImportRefused("import.invalid_schema", "archive zip : fichier trop gros")
                total += len(member)
                if total > MAX_ZIP_TOTAL:
                    raise ImportRefused("import.invalid_schema", "archive zip trop volumineuse")
                out.append(Incoming(f"{Path(name).stem}/{Path(info.filename).name}", member))
    except zipfile.BadZipFile as exc:
        raise ImportRefused("import.invalid_schema", "archive zip illisible") from exc
    return out


class Archiver:
    """Chiffre avec age vers archive/AAAA/MM/ ; la clé publique suffit pour écrire."""

    def __init__(self, root: Path, recipient: str | None, identity_file: Path | None) -> None:
        self.root = root
        self.recipient = recipient
        self.identity_file = identity_file

    def store(self, data: bytes, sub: str, name: str) -> str:
        if self.recipient is None:
            raise ImportRefused(
                "import.archive_unavailable", "clé age absente : archivage impossible"
            )
        target = self.root / sub / f"{name}.age"
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".age.tmp")
        tmp.write_bytes(secrets.encrypt_for(self.recipient, data))
        tmp.replace(target)
        return str(target.relative_to(self.root))

    def load(self, relative: str) -> bytes:
        if self.identity_file is None or not self.identity_file.exists():
            raise ImportRefused(
                "import.archive_unavailable", "clé age absente : relecture impossible"
            )
        return secrets.decrypt_with(self.identity_file, (self.root / relative).read_bytes())


def recipient_from_key(key_file: Path) -> str | None:
    if not key_file.exists():
        return None
    return secrets.recipient(key_file)
