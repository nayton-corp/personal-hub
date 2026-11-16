"""Frais courants publiés des fonds : lecture d'un fichier `isin,ter_pct,origin,on_date` (déposé par
le collecteur « market », market/fees.py, ou à la main), sans rien écrire.

`ter_pct` est en % par an (« 0.2 » pour 0,20 %), `origin` le site où le TER a été lu, `on_date`
le jour de la lecture."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from hub.domains.finance.patrimoine.model import instruments
from hub.domains.finance.patrimoine.model.instruments import DocumentError

SOURCE = "fund_fees"
HEADER = ("isin", "ter_pct", "origin", "on_date")
MAX_BYTES = 256 * 1024
MAX_TER_PCT = Decimal(5)


class FeeFileError(DocumentError):
    pass


@dataclass(frozen=True)
class Fee:
    isin: str
    ter: Decimal  # fraction par an : 0.002 pour 0,20 %
    origin: str
    on_date: str


@dataclass(frozen=True)
class FeeFile:
    fees: list[Fee]

    @property
    def on_date(self) -> str:
        return min((f.on_date for f in self.fees), default="")

    def rows(self) -> list[tuple[int, str | None, str | None]]:
        return [(i, None, f.on_date) for i, f in enumerate(self.fees)]


def _text(data: bytes) -> str:
    return data.lstrip(b"\xef\xbb\xbf").decode("utf-8", errors="replace")


def detect(_name: str, data: bytes) -> str | None:
    if len(data) > MAX_BYTES:
        return None
    head = _text(data[:200]).splitlines()
    ok = bool(head) and tuple(c.strip().lower() for c in head[0].split(",")) == HEADER
    return SOURCE if ok else None


def parse(_source: str, data: bytes) -> FeeFile:
    out: list[Fee] = []
    for n, row in enumerate(csv.DictReader(io.StringIO(_text(data))), start=2):
        isin = (row.get("isin") or "").strip().upper()
        origin = (row.get("origin") or "").strip()[:80]
        try:
            pct = Decimal((row.get("ter_pct") or "").strip().replace(",", "."))
            on = date.fromisoformat((row.get("on_date") or "").strip()).isoformat()
        except (InvalidOperation, ValueError):
            raise FeeFileError(f"ligne {n} : TER ou date illisible") from None
        if not instruments.ISIN.match(isin) or not origin:
            raise FeeFileError(f"ligne {n} : ISIN ou site manquant")
        if not 0 <= pct <= MAX_TER_PCT:
            raise FeeFileError(f"ligne {n} : TER hors de 0 à 5 % par an")
        out.append(Fee(isin, pct / 100, origin, on))
    if not out:
        raise FeeFileError("aucun TER dans le fichier")
    return FeeFile(out)
