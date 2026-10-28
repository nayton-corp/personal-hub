"""Lecture minimale d'un classeur .xlsx : le texte des cellules de la première feuille.

Pas de formules, pas de styles, pas de dates Excel converties : les exports de plateformes
écrivent leurs dates en texte. Un nombre garde son écriture du fichier (« 1.5E-5 »), pour
être lu en `Decimal` sans passer par un flottant. Taille décompressée plafonnée.
"""

from __future__ import annotations

import io
import re
import zipfile
from posixpath import join, normpath

from lxml import etree

MAX_SHEET_BYTES = 64 * 1024 * 1024
MAX_ROWS = 200_000
_MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_PKG = "{http://schemas.openxmlformats.org/package/2006/relationships}"
_COL = re.compile(r"^([A-Z]{1,3})\d+$")


class XlsxError(ValueError):
    pass


def is_xlsx(name: str, data: bytes) -> bool:
    return name.lower().endswith(".xlsx") and data[:4] == b"PK\x03\x04"


def _parser() -> etree.XMLParser:
    return etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False, load_dtd=False)


def _member(z: zipfile.ZipFile, path: str) -> bytes:
    try:
        info = z.getinfo(path)
    except KeyError:
        raise XlsxError(f"classeur incomplet ({path})") from None
    if info.file_size > MAX_SHEET_BYTES:
        raise XlsxError("classeur trop gros")
    with z.open(info) as fh:
        out = fh.read(MAX_SHEET_BYTES + 1)
    if len(out) > MAX_SHEET_BYTES:
        raise XlsxError("classeur trop gros")
    return out


def _xml(z: zipfile.ZipFile, path: str) -> etree._Element:
    try:
        return etree.fromstring(_member(z, path), _parser())
    except etree.XMLSyntaxError:
        raise XlsxError("classeur illisible") from None


def _text(node: etree._Element) -> str:
    return "".join(t.text or "" for t in node.iter(f"{_MAIN}t"))


def _column(ref: str | None, fallback: int) -> int:
    m = _COL.match(ref or "")
    if not m:
        return fallback
    n = 0
    for ch in m.group(1):
        n = n * 26 + ord(ch) - 64
    return n - 1


def _first_sheet(z: zipfile.ZipFile) -> str:
    book = _xml(z, "xl/workbook.xml")
    sheet = book.find(f"{_MAIN}sheets/{_MAIN}sheet")
    if sheet is None:
        raise XlsxError("classeur sans feuille")
    rid = sheet.get(f"{_REL}id")
    rels = _xml(z, "xl/_rels/workbook.xml.rels")
    for rel in rels.iter(f"{_PKG}Relationship"):
        if rel.get("Id") == rid:
            target = rel.get("Target") or ""
            return target.lstrip("/") if target.startswith("/") else normpath(join("xl", target))
    raise XlsxError("classeur sans feuille")


def rows(data: bytes) -> list[list[str]]:
    """Les lignes de la première feuille (index = n° de ligne Excel - 1), chaque cellule en
    texte ('' si vide)."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            path = _first_sheet(z)
            shared: list[str] = []
            if "xl/sharedStrings.xml" in z.namelist():
                sst = _xml(z, "xl/sharedStrings.xml")
                shared = [_text(si) for si in sst.iter(f"{_MAIN}si")]
            sheet = _xml(z, path)
    except zipfile.BadZipFile:
        raise XlsxError("classeur illisible") from None
    out: list[list[str]] = []
    for row in sheet.iter(f"{_MAIN}row"):
        if len(out) >= MAX_ROWS:
            raise XlsxError("trop de lignes")
        number = int(row.get("r") or 0)
        while 0 < len(out) + 1 < number and len(out) < MAX_ROWS:
            out.append([])  # lignes vides absentes du fichier : garder la numérotation d'Excel
        cells: dict[int, str] = {}
        for i, c in enumerate(row.iter(f"{_MAIN}c")):
            kind = c.get("t")
            if kind == "inlineStr":
                value = _text(c)
            else:
                v = c.find(f"{_MAIN}v")
                value = (v.text or "") if v is not None else ""
                if kind == "s" and value:
                    try:
                        value = shared[int(value)]
                    except (ValueError, IndexError):
                        raise XlsxError("classeur illisible") from None
            cells[_column(c.get("r"), i)] = value.strip()
        width = max(cells, default=-1) + 1
        out.append([cells.get(j, "") for j in range(width)])
    return out
