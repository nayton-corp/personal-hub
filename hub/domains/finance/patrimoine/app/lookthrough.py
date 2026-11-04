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
un fonds VIAC rangé par sa sous-catégorie (« Actions Suisse » → la région domestique du pack
pays), sinon « Non ventilé ». Les étiquettes des régions viennent du pack pays (`regions`).
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, localcontext
from typing import Any

from sqlalchemy import Connection, text

from hub.domains.finance.packs.base import CountryPack
from hub.domains.finance.patrimoine.app import valuation
from hub.domains.finance.patrimoine.infra.composition import (
    ASSETS_PER_BUCKET,
    CRYPTO,
    EMERGING,
    JAPAN,
    NORTH_AMERICA,
    PACIFIC,
    TOP,
    UNKNOWN,
    Composition,
    LookthroughFile,
    _norm,
    region_code,
)
from hub.domains.finance.patrimoine.model import instruments
from hub.domains.finance.patrimoine.model.instruments import Result
from hub.kernel.money import DECIMAL_CONTEXT, Money, base_currency


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
                    "w": instruments.price_text(w),
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


def _fallback(
    dimension: str, meta: tuple[str, str | None, str | None, str | None, str], pack: CountryPack
) -> str:
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
    if pack.regions.home and set(hint.split()) & set(pack.regions.home_words):
        return pack.regions.home
    for needle, region in (
        ("emerg", EMERGING),
        ("amerique", NORTH_AMERICA),
        ("usa", NORTH_AMERICA),
        ("japon", JAPAN),
        ("pacifique", PACIFIC),
        ("europe", pack.regions.europe),
    ):
        if needle in hint:
            return region
    return UNKNOWN


def breakdown(conn: Connection, dimension: str, on_date: str, pack: CountryPack) -> dict[str, Any]:
    """Valeur des positions à la date, ventilée selon `dimension` (devise de base, mineures) ;
    chaque case de la région porte son code (`home`, `europe`…) pour le front."""
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
                    put(_fallback(dimension, info, pack), line.isin, Decimal(line.value))
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
                "code": region_code(bucket, pack) if dimension == "region" else None,
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
