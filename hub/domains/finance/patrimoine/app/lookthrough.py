"""Transparence des fonds et des ETF (lot 6) : répartition des positions par région, secteur,
devise, et les dix plus grosses lignes sous-jacentes.

La composition d'un fonds vient d'un fichier déposé dans la boîte d'entrée, sous l'une de ces
deux formes :

- un CSV `isin,dimension,bucket,weight_pct,on_date` (dimension : region, sector, currency ou
  holding ; poids en pour cent), pour recopier une fiche d'émetteur ;
- la liste des lignes d'un fonds telle que l'émetteur la publie (iShares, Vanguard, UBS,
  SPDR… : une ligne d'en-tête avec le poids, le nom, le secteur, le pays et la devise), dont le
  nom de fichier contient l'ISIN du fonds (`IE00B4L5Y983.csv`). Les pays deviennent des régions.

Chaque composition publiée est gardée avec sa date (audit m16) : la répartition à une date lit,
fonds par fonds et dimension par dimension, la dernière composition connue à cette date (ou la
première publiée, pour une date antérieure). La répartition elle-même, liquidités comprises, se
calcule dans allocation.py. Les étiquettes des régions viennent du pack pays (`regions`).
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from sqlalchemy import Connection, text

from hub.domains.finance.patrimoine.infra.composition import Composition, LookthroughFile
from hub.domains.finance.patrimoine.model import instruments
from hub.domains.finance.patrimoine.model.instruments import Result


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
        known = conn.execute(
            text("SELECT 1 FROM compositions WHERE isin = :i AND dimension = :d AND on_date = :on"),
            {"i": c.isin, "d": dim, "on": on},
        ).first()
        if known is not None:
            result.duplicates += 1  # cette composition, à cette date, est déjà là
            continue
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


# --- compositions à une date --------------------------------------------------------------


def compositions_at(
    conn: Connection, dimension: str, on_date: str
) -> tuple[dict[str, list[tuple[str, Decimal]]], dict[str, str]]:
    """({ISIN: [(case, poids)]}, {ISIN: date}) : par fonds, la dernière composition connue à la
    date, sinon la première publiée après."""
    chosen: dict[str, str] = {}
    for isin, on in conn.execute(
        text(
            "SELECT isin, on_date FROM compositions WHERE dimension = :d "
            "GROUP BY isin, on_date ORDER BY isin, on_date"
        ),
        {"d": dimension},
    ):
        if on <= on_date or isin not in chosen:
            chosen[isin] = on
    comps: dict[str, list[tuple[str, Decimal]]] = defaultdict(list)
    for isin, bucket, weight, on in conn.execute(
        text(
            "SELECT isin, bucket, weight, on_date FROM compositions WHERE dimension = :d "
            "ORDER BY isin, bucket"
        ),
        {"d": dimension},
    ):
        if chosen.get(isin) == on:
            comps[isin].append((bucket, Decimal(weight)))
    return comps, chosen
