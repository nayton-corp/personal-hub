"""Fiche mensuelle d'un indice MSCI (PDF public) : la répartition par secteur (GICS) et par pays
de l'indice qu'un fonds indiciel réplique, sans liste de lignes. Le collecteur en tire un petit
CSV générique (`isin,dimension,bucket,weight_pct,on_date`, dimensions `sector` et `country`) au
nom du fonds détenu ; le hub range les pays en régions (patrimoine/infra/composition.py).

La page 2 porte, côte à côte, la légende des secteurs (« Financials 24.75% ») et celle des pays
(cinq premiers et « Other », ou pays de cotation), précédées des seuls pourcentages des
camemberts (format relevé sur les fiches du 30.10.2026 par `pdftotext -layout`). Les onze secteurs
GICS se reconnaissent à leur nom ; le reste est un pays."""

from __future__ import annotations

import csv
import io
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

from hub.kernel import pdf

GICS = (
    "Communication Services",
    "Consumer Discretionary",
    "Consumer Staples",
    "Energy",
    "Financials",
    "Health Care",
    "Industrials",
    "Information Technology",
    "Materials",
    "Real Estate",
    "Utilities",
)
START = "SECTOR WEIGHTS"
# « Financials 24.75% », « Hong Kong SAR China 47.12% » : un nom, puis un pourcentage
PAIR = re.compile(r"([A-Za-z][A-Za-z .,&'()-]*?)\s+(\d{1,3}(?:\.\d+)?)\s?%")
AS_OF = re.compile(r"\(([A-Z][a-z]{2}|[A-Z]{3}) (\d{1,2}), (\d{4})\)")
TOLERANCE = Decimal(2)  # points de pourcentage : une légende incomplète est refusée


class SheetError(ValueError):
    pass


def _date(text: str) -> str:
    m = AS_OF.search(text)
    if m is None:
        raise SheetError("fiche sans date")
    raw = f"{m.group(1).title()} {m.group(2)} {m.group(3)}"
    return datetime.strptime(raw, "%b %d %Y").date().isoformat()  # noqa: DTZ007 - date seule


def weights(text: str) -> tuple[str, list[tuple[str, Decimal]], list[tuple[str, Decimal]]]:
    """(date, secteurs, pays) de la fiche ; refus si l'une des deux légendes ne fait pas 100."""
    at = text.find(START)
    if at < 0:
        raise SheetError("fiche sans répartition par secteur")
    block = text[at:].split("\f", 1)[0]  # jusqu'à la fin de la page
    sectors: list[tuple[str, Decimal]] = []
    countries: list[tuple[str, Decimal]] = []
    for line in block.splitlines()[1:]:  # la ligne des titres, puis camemberts et légendes
        for name, value in PAIR.findall(line):
            try:
                pct = Decimal(value)
            except InvalidOperation:
                continue
            label = " ".join(name.split())
            (sectors if label in GICS else countries).append((label, pct))
    for found in (sectors, countries):
        if not found or abs(sum(w for _n, w in found) - 100) > TOLERANCE:
            raise SheetError("répartition incomplète")
    return _date(text), sectors, countries


def to_csv(isin: str, data: bytes) -> bytes:
    """Le CSV générique d'un fonds à partir de la fiche PDF de son indice."""
    try:
        text = pdf.pdftotext(data)
    except pdf.PdfError as exc:
        raise SheetError(str(exc)) from None
    on, sectors, countries = weights(text)
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(["isin", "dimension", "bucket", "weight_pct", "on_date"])
    for dim, rows in (("sector", sectors), ("country", countries)):
        for name, pct in rows:
            w.writerow([isin, dim, name, pct, on])
    return out.getvalue().encode()
