"""Transparence des fonds et des ETF (lot 6) : répartition des positions par région, secteur,
devise, et les dix plus grosses lignes sous-jacentes.

La composition d'un fonds vient d'un fichier déposé dans la boîte d'entrée, sous l'une de ces
deux formes :

- un CSV `isin,dimension,bucket,weight_pct,on_date` (dimension : region, sector, currency ou
  holding ; poids en pour cent), pour recopier une fiche d'émetteur ;
- la liste des lignes d'un fonds telle que l'émetteur la publie (iShares, Vanguard, UBS,
  SPDR… : une ligne d'en-tête avec le poids, le nom, le secteur, le pays et la devise), dont le
  nom de fichier contient l'ISIN du fonds (`IE00B4L5Y983.csv`). Les pays deviennent des régions.

Une composition plus récente remplace l'ancienne, dimension par dimension. Une position sans
composition garde ce que l'on sait d'elle : sa devise de cotation, une crypto en « Crypto »,
un fonds VIAC rangé par sa sous-catégorie (« Actions Suisse » → Suisse), sinon « Non ventilé ».
"""

from __future__ import annotations

import csv
import io
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, localcontext
from typing import Any

from sqlalchemy import Connection, text

from hub.core.money import DECIMAL_CONTEXT, Money, base_currency
from hub.core.text import normalize
from hub.domains.finance import assets, valuation
from hub.domains.finance.assets import AssetError, DocumentError, Result

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
EUROPE = "Europe (hors Suisse)"
SWITZERLAND = "Suisse"
JAPAN = "Japon"
PACIFIC = "Pacifique (hors Japon)"
EMERGING = "Marchés émergents"
OTHER = "Autres"
# pays (anglais, français, allemand), normalisés → région
COUNTRIES: dict[str, str] = {}
for _region, _names in {
    NORTH_AMERICA: "united states|etats-unis|usa|us|vereinigte staaten|canada|kanada",
    SWITZERLAND: "switzerland|suisse|schweiz|ch",
    EUROPE: (
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
        COUNTRIES[_n] = _region

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
    return m.group(1) if m and assets.ISIN.match(m.group(1)) else None


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
        return assets.number(v)
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


def region_of(country: str) -> str:
    return COUNTRIES.get(_norm(country), OTHER) if country.strip() else UNKNOWN


def _parse_generic(data: bytes) -> LookthroughFile:
    by_isin: dict[str, list[Weight]] = defaultdict(list)
    dates: dict[str, str] = {}
    for n, raw in enumerate(csv.DictReader(io.StringIO(_text(data)))):
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items()}
        if not any(row.values()):
            continue
        isin = row["isin"].upper()
        if not assets.ISIN.match(isin):
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


def _parse_list(isin: str, data: bytes) -> LookthroughFile:
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
            sums["region"][region_of(cell(c_col))] += pct
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


def parse(source: str, data: bytes) -> LookthroughFile:
    if len(data) > MAX_BYTES:
        raise LookthroughError("fichier trop volumineux")
    if source == SOURCE:
        return _parse_generic(data)
    isin = source.split(":", 1)[1] if ":" in source else ""
    if not assets.ISIN.match(isin):
        raise LookthroughError("ISIN du fonds absent du nom de fichier")
    return _parse_list(isin, data)


def apply_composition(conn: Connection, import_id: str, c: Composition) -> Result:
    result = Result()
    on = (
        c.on_date
        or str(
            conn.execute(
                text("SELECT received_at FROM imports WHERE id = :i"), {"i": import_id}
            ).scalar_one()
        )[:10]
    )
    for dim in sorted({w.dimension for w in c.weights}):
        current = conn.execute(
            text("SELECT max(on_date) FROM compositions WHERE isin = :i AND dimension = :d"),
            {"i": c.isin, "d": dim},
        ).scalar_one()
        if current is not None and current > on:
            result.duplicates += 1  # une composition plus récente est déjà là
            continue
        conn.execute(
            text("DELETE FROM compositions WHERE isin = :i AND dimension = :d"),
            {"i": c.isin, "d": dim},
        )
        merged: dict[str, Decimal] = defaultdict(Decimal)
        for w in c.weights:
            if w.dimension == dim:
                merged[w.bucket] += w.weight
        conn.execute(
            text(
                "INSERT INTO compositions (isin, dimension, bucket, weight, on_date, import_id) "
                "VALUES (:i, :d, :b, :w, :on, :imp)"
            ),
            [
                {
                    "i": c.isin,
                    "d": dim,
                    "b": b,
                    "w": assets.price_text(w),
                    "on": on,
                    "imp": import_id,
                }
                for b, w in sorted(merged.items())
            ],
        )
        result.new += 1
    return result


def apply(
    conn: Connection, import_id: str, doc: LookthroughFile, indexes: set[int] | None
) -> list[tuple[int, Result]]:
    return [
        (i, apply_composition(conn, import_id, c))
        for i, c in enumerate(doc.compositions)
        if indexes is None or i in indexes
    ]


# --- répartition --------------------------------------------------------------------------


def _fallback(dimension: str, meta: tuple[str, str | None, str | None, str | None, str]) -> str:
    """Rangement d'une position sans composition publiée."""
    name, asset_class, sub_class, currency, kind = meta
    if dimension == "holding":
        return name
    if kind == "crypto":
        return CRYPTO if dimension != "currency" else (currency or CRYPTO)
    if dimension == "currency":
        return currency or UNKNOWN
    hint = _norm(f"{asset_class or ''} {sub_class or ''}")
    if dimension == "sector":
        if "immobilier" in hint:
            return "Immobilier"
        if "obligation" in hint:
            return "Obligations"
        if "liquidit" in hint or "monetaire" in hint:
            return "Liquidités et dérivés"
        return UNKNOWN
    for needle, region in (
        ("suisse", SWITZERLAND),
        ("emerg", EMERGING),
        ("amerique", NORTH_AMERICA),
        ("usa", NORTH_AMERICA),
        ("japon", JAPAN),
        ("pacifique", PACIFIC),
        ("europe", EUROPE),
    ):
        if needle in hint:
            return region
    return UNKNOWN


def breakdown(conn: Connection, dimension: str, on_date: str) -> dict[str, Any]:
    """Valeur des positions à la date, ventilée selon `dimension` (CHF, centimes)."""
    positions = valuation.Positions(conn)
    meta = {
        r[0]: (r[1], r[2], r[3], r[4], r[5])
        for r in conn.execute(
            text("SELECT isin, name, asset_class, sub_class, currency, kind FROM instruments")
        )
    }
    comps: dict[str, list[tuple[str, Decimal]]] = defaultdict(list)
    dates: dict[str, str] = {}
    for isin, bucket, weight, on in conn.execute(
        text("SELECT isin, bucket, weight, on_date FROM compositions WHERE dimension = :d"),
        {"d": dimension},
    ):
        comps[isin].append((bucket, Decimal(weight)))
        dates[isin] = on
    sums: dict[str, Decimal] = defaultdict(Decimal)
    # qui remplit chaque case : bucket → ISIN → valeur (l'app montre les actifs d'un bloc)
    parts: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))

    def put(bucket: str, isin: str, value: Decimal) -> None:
        sums[bucket] += value
        parts[bucket][isin] += value

    total = covered = 0
    with localcontext(DECIMAL_CONTEXT):
        for account_id in sorted(positions.accounts):
            for line in positions.lines(account_id, on_date):
                if line.price is None or line.value <= 0:
                    continue
                total += line.value
                if line.isin in comps:
                    covered += line.value
                    weights = comps[line.isin]
                    assigned = sum((w for _b, w in weights), Decimal(0))
                    for bucket, w in weights:
                        put(bucket, line.isin, line.value * w)
                    if dimension != "holding" and assigned < 1:
                        put(UNKNOWN, line.isin, line.value * (1 - assigned))
                    elif dimension == "holding" and assigned < 1:
                        put("Autres lignes", line.isin, line.value * (1 - assigned))
                else:
                    info = meta.get(line.isin, (line.isin, None, None, line.currency, "other"))
                    put(_fallback(dimension, info), line.isin, Decimal(line.value))
    found: list[tuple[str, int]] = []
    for bucket, value in sums.items():
        minor = int(value.to_integral_value())
        if minor > 0:
            found.append((bucket, minor))
    rest = [x for x in found if x[0] in (UNKNOWN, "Autres lignes")]
    ranked = sorted((x for x in found if x not in rest), key=lambda x: (-x[1], x[0]))
    if dimension == "holding":
        ranked = ranked[:TOP]
    out = []
    for bucket, minor in ranked + rest:
        weight = None
        if total:
            with localcontext(DECIMAL_CONTEXT):
                weight = str((Decimal(minor) / total).quantize(Decimal("0.0001")))
        assets = sorted(parts[bucket].items(), key=lambda x: (-x[1], x[0]))[:ASSETS_PER_BUCKET]
        out.append(
            {
                "bucket": bucket,
                "value": Money(minor, base_currency()).to_api(),
                "weight": weight,
                "assets": [
                    {
                        "isin": isin,
                        "name": meta.get(isin, (isin,))[0],
                        "value": Money(int(v.to_integral_value()), base_currency()).to_api(),
                    }
                    for isin, v in assets
                    if v >= 1
                ],
            }
        )
    since = min(dates.values(), default=None)
    return {
        "dimension": dimension,
        "on_date": on_date,
        "currency": base_currency(),
        "total": Money(total, base_currency()).to_api(),
        "covered": (str((Decimal(covered) / total).quantize(Decimal("0.0001"))) if total else None),
        "compositions_since": since,
        "items": out,
    }
