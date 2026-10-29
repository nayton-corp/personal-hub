"""Dépôt atomique dans la boîte d'entrée, et contrôle de forme du fichier avant de le montrer.

Le téléchargement va dans `inbox/.tmp/`, puis le fichier est contrôlé (forme du format attendu,
empreinte déjà vue) et seulement alors renommé dans `inbox/` : le pipeline ne voit jamais un
fichier à moitié écrit. Un fichier non conforme part dans `inbox/quarantine/`. Le contrôle reste
superficiel (racine camt.053, en-tête PDF, JSON attendu) : le XSD et la lecture complète restent
au parseur du domaine Finance, que les collecteurs n'importent pas.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import zipfile
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from lxml import etree

from hub.collectors.base import Failure, Memory
from hub.kernel.clock import utcnow

CAMT053 = "urn:iso:std:iso:20022:tech:xsd:camt.053.001."
MAX_BYTES = 50 * 1024 * 1024
_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def _xml_parser() -> etree.XMLParser:
    return etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False, load_dtd=False)


def is_camt053(data: bytes) -> bool:
    if b"<!ENTITY" in data[:4096]:
        return False
    try:
        root = etree.fromstring(data, _xml_parser())
    except etree.XMLSyntaxError:
        return False
    ns = etree.QName(root).namespace or ""
    return ns.startswith(CAMT053) and root.find(f"{{{ns}}}BkToCstmrStmt") is not None


def is_camt_zip(data: bytes) -> bool:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            members = [i for i in z.infolist() if not i.is_dir()]
            if not members or len(members) > 500:
                return False
            for info in members:
                if info.file_size > MAX_BYTES or not info.filename.lower().endswith(".xml"):
                    return False
                if not is_camt053(z.read(info)):
                    return False
    except zipfile.BadZipFile:
        return False
    return True


def is_camt_export(data: bytes) -> bool:
    return is_camt_zip(data) if data[:2] == b"PK" else is_camt053(data)


def is_pdf(data: bytes) -> bool:
    return data[:5] == b"%PDF-" and b"%%EOF" in data[-1024:]


def is_revolut_json(data: bytes) -> bool:
    try:
        doc = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    return (
        isinstance(doc, dict)
        and doc.get("format") == "hub.revolut.v1"
        and isinstance(doc.get("transactions"), list)
        and isinstance(doc.get("account"), dict)
    )


def is_flex(data: bytes) -> bool:
    """Relevé Flex Query IBKR (lot 6) : racine `FlexQueryResponse` avec ses relevés."""
    if b"<!ENTITY" in data[:4096] or b"<!DOCTYPE" in data[:4096]:
        return False
    try:
        root = etree.fromstring(data, _xml_parser())
    except etree.XMLSyntaxError:
        return False
    return root.tag == "FlexQueryResponse" and root.find("FlexStatements") is not None


def is_market_json(data: bytes) -> bool:
    try:
        doc = json.loads(data, parse_float=str)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    return isinstance(doc, dict) and doc.get("format") == "hub.market.v1"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe(name: str) -> str:
    return _SAFE.sub("-", name).strip("-")[:80] or "fichier"


class Inbox:
    def __init__(self, root: Path, memory: Memory) -> None:
        self.root = root
        self.memory = memory
        self.tmp = root / ".tmp"
        self.quarantine = root / "quarantine"

    def stamp(self) -> str:
        return utcnow().strftime("%Y%m%dT%H%M%S")

    def drop(self, name: str, data: bytes, check: Callable[[bytes], bool], *, step: str) -> bool:
        """Dépose `data` sous `name` ; False si déjà vu. Lève `invalid_file` après quarantaine."""
        if len(data) > MAX_BYTES:
            raise Failure("invalid_file", f"{step}:too_large")
        digest = sha256(data)
        if digest in self.memory.seen():
            return False
        self.tmp.mkdir(parents=True, exist_ok=True)
        # l'empreinte départage deux fichiers de même nom déposés dans la même seconde
        part = self.tmp / f"{self.stamp()}-{digest[:8]}-{safe(name)}"
        part.write_bytes(data)
        if not check(data):
            self.quarantine.mkdir(parents=True, exist_ok=True)
            os.replace(part, self.quarantine / part.name)
            raise Failure("invalid_file", step)
        target = self.root / f"{part.name}"
        os.replace(part, target)  # même volume : renommage atomique
        self.memory.remember(digest)
        return True

    def clean_tmp(self, older_than: datetime) -> int:
        """Restes d'un run interrompu."""
        count = 0
        if self.tmp.is_dir():
            for p in self.tmp.iterdir():
                if p.is_file() and p.stat().st_mtime < older_than.timestamp():
                    p.unlink()
                    count += 1
        return count
