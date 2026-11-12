"""Compositions de fonds et d'ETF (lot 6) : lecture d'un fichier déposé (format générique ou liste
de lignes d'un émetteur) en poids par région, secteur, devise et ligne, sans rien écrire."""

from __future__ import annotations

import csv
import io
import re
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, localcontext
from types import MappingProxyType

from hub.domains.finance.packs import instance as packs
from hub.domains.finance.packs.base import CountryPack
from hub.domains.finance.patrimoine.model import instruments
from hub.domains.finance.patrimoine.model.instruments import AssetError, DocumentError
from hub.kernel.money import DECIMAL_CONTEXT
from hub.kernel.text import normalize

SOURCE = "lookthrough"
DIMENSIONS = ("region", "sector", "currency", "holding")
GENERIC_HEADER = ("isin", "dimension", "bucket", "weight_pct", "on_date")
MAX_BYTES = 10 * 1024 * 1024
TOP = 10
ASSETS_PER_BUCKET = 5  # actifs nommés sous chaque case de la répartition
UNKNOWN = "Non ventilé"
CRYPTO = "Crypto"
_ISIN_IN_NAME = re.compile(r"([A-Z]{2}[A-Z0-9]{9}\d)")
NORTH_AMERICA = "Amérique du Nord"
EUROPE = "Europe"  # étiquette générique ; le pack pays la remplace (« Europe (hors Suisse) »)
JAPAN = "Japon"
PACIFIC = "Pacifique (hors Japon)"
EMERGING = "Marchés émergents"
OTHER = "Autres"
# codes de région publiés par l'API (le front choisit l'icône) ; `home` : la région domestique
CODES = {
    NORTH_AMERICA: "north_america",
    EUROPE: "europe",
    JAPAN: "japan",
    PACIFIC: "pacific",
    EMERGING: "emerging",
    OTHER: "other",
    UNKNOWN: "unknown",
    CRYPTO: "crypto",
}
# pays (anglais, français, allemand), normalisés → région ; la région domestique du pack pays
# (« Suisse ») est reconnue avant, par ses mots
_countries: dict[str, str] = {}
for _region, _names in {
    NORTH_AMERICA: "united states|etats-unis|usa|us|vereinigte staaten|canada|kanada",
    EUROPE: (
        "switzerland|suisse|schweiz|ch|"
        "united kingdom|royaume-uni|grossbritannien|uk|france|frankreich|germany|allemagne|"
        "deutschland|netherlands|pays-bas|niederlande|sweden|suede|schweden|denmark|danemark|"
        "danemark|daenemark|spain|espagne|spanien|italy|italie|italien|finland|finlande|"
        "finnland|norway|norvege|norwegen|belgium|belgique|belgien|ireland|irlande|irland|"
        "austria|autriche|oesterreich|osterreich|portugal|luxembourg|luxemburg|jersey|guernsey|"
        "isle of man|faroe islands|liechtenstein|monaco"
    ),
    JAPAN: "japan|japon",
    PACIFIC: (
        "australia|australie|australien|hong kong|singapore|singapour|singapur|new zealand|"
        "nouvelle-zelande|neuseeland|israel|macau|macao"
    ),
    EMERGING: (
        "china|chine|taiwan|india|inde|indien|korea (south)|korea|south korea|coree du sud|"
        "sudkorea|brazil|bresil|brasilien|saudi arabia|arabie saoudite|south africa|"
        "afrique du sud|mexico|mexique|mexiko|indonesia|indonesie|thailand|thailande|malaysia|"
        "malaisie|united arab emirates|emirats arabes unis|qatar|poland|pologne|polen|turkey|"
        "turquie|turkei|chile|chili|philippines|greece|grece|kuwait|koweit|peru|perou|hungary|"
        "hongrie|czech republic|republique tcheque|colombia|colombie|egypt|egypte"
    ),
}.items():
    for _n in _names.split("|"):
        _countries[_n] = _region
COUNTRIES: Mapping[str, str] = MappingProxyType(_countries)  # gelé (audit m16)
# colonnes d'une liste de lignes d'émetteur, en minuscules sans accents
WEIGHT_COLS = (
    "weight (%)",
    "weight",
    "% of net assets",
    "% of funds",
    "poids (%)",
    "poids",
    "gewichtung (%)",
    "gewichtung",
    "% net assets",
    "% of market value",
)
NAME_COLS = ("name", "nom", "holding", "issuer", "security name", "description")
SECTOR_COLS = ("sector", "secteur", "sektor", "gics sector")
COUNTRY_COLS = ("location", "country", "pays", "land", "domicile", "location of risk")
CURRENCY_COLS = ("market currency", "currency", "devise", "wahrung", "currency code")
CLASS_COLS = ("asset class", "classe d'actifs", "anlageklasse")
SECTORS = {
    "information technology": "Technologie",
    "technologie de l'information": "Technologie",
    "it": "Technologie",
    "financials": "Finance",
    "finance": "Finance",
    "health care": "Santé",
    "sante": "Santé",
    "consumer discretionary": "Consommation discrétionnaire",
    "consumer staples": "Consommation de base",
    "industrials": "Industrie",
    "communication": "Communication",
    "communication services": "Communication",
    "energy": "Énergie",
    "materials": "Matériaux",
    "utilities": "Services publics",
    "real estate": "Immobilier",
    "cash and/or derivatives": "Liquidités et dérivés",
    "cash": "Liquidités et dérivés",
}


class LookthroughError(DocumentError):
    pass


@dataclass(frozen=True)
class Weight:
    dimension: str
    bucket: str
    weight: Decimal  # fraction, entre 0 et 1


@dataclass(frozen=True)
class Composition:
    isin: str
    on_date: str | None  # None : date du fichier inconnue, celle de l'import la remplace
    weights: list[Weight]


@dataclass(frozen=True)
class LookthroughFile:
    compositions: list[Composition]

    @property
    def on_date(self) -> str:
        return min((c.on_date or "" for c in self.compositions), default="")

    def rows(self) -> list[tuple[int, str | None, str | None]]:
        return [(i, None, c.on_date) for i, c in enumerate(self.compositions)]


def _text(data: bytes) -> str:
    raw = data.lstrip(b"\xef\xbb\xbf")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def _norm(value: str) -> str:
    return normalize(value).strip()


def isin_from_name(name: str) -> str | None:
    m = _ISIN_IN_NAME.search(name.upper())
    return m.group(1) if m and instruments.ISIN.match(m.group(1)) else None


def is_generic(data: bytes) -> bool:
    head = _text(data[:400]).splitlines()
    return bool(head) and tuple(c.strip().lower() for c in head[0].split(",")) == GENERIC_HEADER


def _sniff(lines: list[str]) -> tuple[int, str] | None:
    """(rang de la ligne d'en-tête, séparateur) d'une liste de lignes d'émetteur."""
    for i, line in enumerate(lines[:40]):
        for sep in (",", ";", "\t"):
            cells = [_norm(c.strip().strip('"')) for c in line.split(sep)]
            if any(c in WEIGHT_COLS for c in cells) and any(c in NAME_COLS for c in cells):
                return i, sep
    return None


def detect(name: str, data: bytes) -> str | None:
    """`lookthrough` (CSV générique) ou `lookthrough:<ISIN>` (liste de l'émetteur)."""
    if len(data) > MAX_BYTES:
        return None
    if is_generic(data):
        return SOURCE
    isin = isin_from_name(name)
    if isin and _sniff(_text(data[:20000]).splitlines()):
        return f"{SOURCE}:{isin}"
    return None


def _pct(value: str) -> Decimal | None:
    v = value.replace("%", "").strip()
    if not v or v in ("-", "--"):
        return None
    try:
        return instruments.number(v)
    except AssetError:
        return None


def _fraction(pct: Decimal) -> Decimal:
    with localcontext(DECIMAL_CONTEXT):
        return pct / 100


def _date(value: str) -> str | None:
    v = value.strip().strip('"')
    for fmt in (
        "%Y-%m-%d",
        "%d.%m.%Y",
        "%d/%m/%Y",
        "%m/%d/%Y",
        "%d/%b/%Y",  # iShares : « 10/Nov/2026 »
        "%b %d, %Y",
        "%d %b %Y",
        "%B %d, %Y",
        "%d-%b-%Y",
    ):
        try:
            return datetime.strptime(v, fmt).date().isoformat()  # noqa: DTZ007 - date seule
        except ValueError:
            continue
    return None


def region_of(country: str, pack: CountryPack) -> str:
    """La région d'un pays : la région domestique du pack si le pays en est, sinon la région
    générique, l'Europe sous l'étiquette du pack."""
    if country.strip() in ("", "-", "--"):  # liquidités et dérivés d'un fonds : sans pays
        return UNKNOWN
    word = _norm(country)
    if pack.regions.home and word in pack.regions.home_words:
        return pack.regions.home
    region = COUNTRIES.get(word, OTHER)
    return pack.regions.europe if region == EUROPE else region


def region_code(bucket: str, pack: CountryPack) -> str | None:
    """Le code d'une case de la répartition par région (None : une étiquette libre)."""
    if pack.regions.home and bucket == pack.regions.home:
        return "home"
    if bucket == pack.regions.europe:
        return CODES[EUROPE]
    return CODES.get(bucket)


def _parse_generic(data: bytes) -> LookthroughFile:
    by_isin: dict[str, list[Weight]] = defaultdict(list)
    dates: dict[str, str] = {}
    for n, raw in enumerate(csv.DictReader(io.StringIO(_text(data)))):
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items()}
        if not any(row.values()):
            continue
        isin = row["isin"].upper()
        if not instruments.ISIN.match(isin):
            raise LookthroughError(f"ligne {n + 2} : ISIN illisible")
        dim = row["dimension"].lower()
        if dim not in DIMENSIONS:
            raise LookthroughError(f"ligne {n + 2} : dimension inconnue ({dim})")
        pct = _pct(row["weight_pct"])
        if pct is None or not (0 <= pct <= 100) or not row["bucket"]:
            raise LookthroughError(f"ligne {n + 2} : poids ou nom illisible")
        on = _date(row["on_date"])
        if on is None:
            raise LookthroughError(f"ligne {n + 2} : date illisible (AAAA-MM-JJ)")
        dates[isin] = max(dates.get(isin, on), on)
        by_isin[isin].append(Weight(dim, row["bucket"][:80], _fraction(pct)))
    if not by_isin:
        raise LookthroughError("fichier vide")
    return LookthroughFile([Composition(i, dates[i], w) for i, w in sorted(by_isin.items())])


def _col(header: list[str], names: tuple[str, ...]) -> int | None:
    for n in names:
        if n in header:
            return header.index(n)
    return None


def _parse_list(isin: str, data: bytes, pack: CountryPack) -> LookthroughFile:
    lines = _text(data).splitlines()
    found = _sniff(lines)
    if found is None:
        raise LookthroughError("liste de lignes sans colonne de poids")
    start, sep = found
    on_date = None
    for line in lines[:start]:  # « Fund Holdings as of, "Oct 24, 2026" »
        cells = next(csv.reader([line], delimiter=sep), [])
        for c in cells[1:]:
            on_date = on_date or _date(c)
    rows = list(csv.reader(lines[start:], delimiter=sep))
    header = [_norm(c) for c in rows[0]]
    w_col = _col(header, WEIGHT_COLS)
    n_col = _col(header, NAME_COLS)
    if w_col is None or n_col is None:
        raise LookthroughError("liste de lignes sans colonne de poids")
    s_col = _col(header, SECTOR_COLS)
    c_col = _col(header, COUNTRY_COLS)
    ccy_col = _col(header, CURRENCY_COLS)
    a_col = _col(header, CLASS_COLS)
    sums: dict[str, dict[str, Decimal]] = {d: defaultdict(Decimal) for d in DIMENSIONS}
    total = Decimal(0)
    with localcontext(DECIMAL_CONTEXT):
        for cells in rows[1:]:
            if len(cells) <= max(w_col, n_col):
                continue
            pct = _pct(cells[w_col])
            if pct is None or pct == 0:
                continue
            total += pct

            def cell(i: int | None, row: list[str] = cells) -> str:
                return row[i].strip() if i is not None and i < len(row) else ""

            klass = _norm(cell(a_col))
            sector = cell(s_col)
            if klass in ("cash", "money market", "futures", "fx", "cash collateral and margins"):
                sector = "Cash"
            sums["sector"][SECTORS.get(_norm(sector), sector or UNKNOWN)] += pct
            sums["region"][region_of(cell(c_col), pack)] += pct
            sums["currency"][(cell(ccy_col) or UNKNOWN).upper()[:12]] += pct
            sums["holding"][cell(n_col)[:80] or UNKNOWN] += pct
        if total <= 0:
            raise LookthroughError("liste de lignes vide")
        weights = []
        for dim in ("region", "sector", "currency"):
            weights += [Weight(dim, b, v / total) for b, v in sorted(sums[dim].items())]
        top = sorted(sums["holding"].items(), key=lambda kv: (-kv[1], kv[0]))[:TOP]
        weights += [Weight("holding", b, v / total) for b, v in top]
    return LookthroughFile([Composition(isin, on_date, weights)])


def parse(source: str, data: bytes, pack: CountryPack | None = None) -> LookthroughFile:
    """`pack` : le pack pays qui nomme les régions (celui de l'instance par défaut)."""
    if len(data) > MAX_BYTES:
        raise LookthroughError("fichier trop volumineux")
    if source == SOURCE:
        return _parse_generic(data)
    isin = source.split(":", 1)[1] if ":" in source else ""
    if not instruments.ISIN.match(isin):
        raise LookthroughError("ISIN du fonds absent du nom de fichier")
    return _parse_list(isin, data, pack or packs.current())
