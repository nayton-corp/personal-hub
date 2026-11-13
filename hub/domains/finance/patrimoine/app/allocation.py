"""Répartition du patrimoine affiché, par région, secteur ou devise (audit du 10/11, lot B) : un
seul calcul, côté serveur, sur les lignes de la série (model/engine.py). Ce sont les lignes que
l'écran montre (comptes non masqués par défaut, sinon la sélection `ids`), valorisées comme la
courbe : la somme des cases, dettes retranchées à part, est le patrimoine affiché.

Chaque franc arrive dans une case par un chemin connu :

- la composition publiée d'un fonds (lookthrough.py) : sûr ; la part qu'elle ne détaille pas va
  dans « Non réparti » ;
- les liquidités d'un compte : une case « Liquidités » (par devise : la devise du compte) ;
- une crypto : « Crypto » ;
- sans composition, ce que l'on sait de l'instrument : sa classe (« Immobilier », « Actions
  Suisse »…) ou sa devise de cotation. C'est une estimation, dite comme telle ;
- sinon « Secteur inconnu », « Région inconnue », « Devise inconnue » : un actif sans fiche.

`covered` est la part sûre du total : ni estimée, ni non répartie, ni inconnue. Une position sans
cours n'a pas de valeur : elle est nommée dans `unpriced`, hors de la répartition.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from decimal import Decimal, localcontext
from typing import Any

from sqlalchemy import Connection, text

from hub.domains.finance.packs.base import CountryPack
from hub.domains.finance.patrimoine.app import perf_lines
from hub.domains.finance.patrimoine.app.lookthrough import compositions_at
from hub.domains.finance.patrimoine.infra.composition import (
    ASSETS_PER_BUCKET,
    CRYPTO,
    EMERGING,
    JAPAN,
    NORTH_AMERICA,
    PACIFIC,
    TOP,
    UNKNOWN,
    _norm,
    region_code,
)
from hub.domains.finance.patrimoine.model.engine import ABSENT
from hub.kernel.money import DECIMAL_CONTEXT, Money, base_currency

CASH = "Liquidités"
NOT_SPLIT = "Non réparti"
OTHER_LINES = "Autres lignes"
UNKNOWN_OF = {
    "region": "Région inconnue",
    "sector": "Secteur inconnu",
    "currency": "Devise inconnue",
}
# nature d'une case : nommée, liquidités, part non détaillée par un fonds, actif sans fiche
NAMED, CASH_KIND, UNDETAILED, UNKNOWN_KIND = "named", "cash", "undetailed", "unknown"
_LAST = {UNDETAILED: 1, UNKNOWN_KIND: 2}
_DIRECT = ("stock", "bond")  # un titre en direct : sa devise de cotation est sa devise

Meta = tuple[str, str | None, str | None, str | None, str]


def classify(dimension: str, meta: Meta, pack: CountryPack) -> tuple[str, str, bool]:
    """(case, nature, estimé) d'une position sans composition publiée."""
    name, asset_class, sub_class, currency, kind = meta
    unknown = (UNKNOWN_OF.get(dimension, UNKNOWN), UNKNOWN_KIND, False)
    if dimension == "holding":
        return name, NAMED, False
    if kind == "crypto":
        return (CRYPTO if dimension != "currency" else (currency or CRYPTO)), NAMED, False
    if dimension == "currency":
        return (currency, NAMED, kind not in _DIRECT) if currency else unknown
    hint = _norm(f"{asset_class or ''} {sub_class or ''}")
    if dimension == "sector":
        for needle, sector in (
            ("immobilier", "Immobilier"),
            ("obligation", "Obligations"),
            ("liquidit", "Liquidités et dérivés"),
            ("monetaire", "Liquidités et dérivés"),
        ):
            if needle in hint:
                return sector, NAMED, True
        return unknown
    if pack.regions.home and set(hint.split()) & set(pack.regions.home_words):
        return pack.regions.home, NAMED, True
    for needle, region in (
        ("emerg", EMERGING),
        ("amerique", NORTH_AMERICA),
        ("usa", NORTH_AMERICA),
        ("japon", JAPAN),
        ("pacifique", PACIFIC),
        ("europe", pack.regions.europe),
    ):
        if needle in hint:
            return region, NAMED, True
    return unknown


class _Buckets:
    """Les cases en construction : valeur, part estimée, et qui les remplit."""

    def __init__(self) -> None:
        self.value: dict[str, Decimal] = defaultdict(Decimal)
        self.estimated: dict[str, Decimal] = defaultdict(Decimal)
        self.kind: dict[str, str] = {}
        # case → (ISIN ou None, compte ou None) → valeur : l'app montre les actifs d'un bloc
        self.parts: dict[str, dict[tuple[str | None, str | None], Decimal]] = defaultdict(
            lambda: defaultdict(Decimal)
        )

    def put(
        self,
        bucket: str,
        kind: str,
        value: Decimal,
        *,
        isin: str | None = None,
        account: str | None = None,
        estimated: bool = False,
    ) -> None:
        self.value[bucket] += value
        self.kind.setdefault(bucket, kind)
        self.parts[bucket][(isin, account)] += value
        if estimated:
            self.estimated[bucket] += value


def _empty(dimension: str, on_date: str, ccy: str) -> dict[str, Any]:
    zero = Money(0, ccy).to_api()
    return {
        "dimension": dimension,
        "on_date": on_date,
        "currency": ccy,
        "total": zero,
        "owed": zero,
        "covered": None,
        "compositions_since": None,
        "items": [],
        "unpriced": [],
    }


def breakdown(
    conn: Connection,
    dimension: str,
    on_date: str,
    pack: CountryPack,
    ids: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Les lignes `ids` (celles de l'app par défaut) à la date, ventilées selon `dimension`, dans
    la devise de base. `total` : ce qui est réparti, égal à la somme des cases ; `owed` : dettes
    et soldes négatifs, à part ; `total + owed` est la valeur de la sélection (la courbe)."""
    ccy = base_currency()
    s = perf_lines.engine_for(conn, on_date)
    if s is None or on_date < s.days[0]:
        return _empty(dimension, on_date, ccy)
    k = s.index(on_date)
    chosen = [s.lines[i] for i in (ids if ids else s.default_ids()) if i in s.lines]
    meta: dict[str, Meta] = {
        r[0]: (r[1], r[2], r[3], r[4], r[5])
        for r in conn.execute(
            text("SELECT isin, name, asset_class, sub_class, currency, kind FROM instruments")
        )
    }
    accounts = {
        r[0]: (r[1] if r[1] == r[2] else f"{r[1]} · {r[2]}", r[3])
        for r in conn.execute(text("SELECT id, institution, name, kind FROM accounts"))
    }
    comps, dates = compositions_at(conn, dimension, on_date)
    holding = dimension == "holding"
    b = _Buckets()
    owed = 0
    used: set[str] = set()
    unpriced: dict[tuple[str, str], None] = {}
    with localcontext(DECIMAL_CONTEXT):
        for ln in chosen:
            v = ln.value[k]
            if ln.kind == "position" and ln.missing[k]:
                unpriced[(ln.account_id, ln.asset[5:])] = None
            if v == ABSENT or v == 0:
                continue
            if ln.kind == "debt" or v < 0:
                owed += 0 if holding else v
            elif ln.kind == "cash":
                if holding:
                    continue
                crypto = accounts.get(ln.account_id, ("", ""))[1] == "crypto"
                if dimension == "currency":
                    b.put(ln.asset[4:], NAMED, Decimal(v), account=ln.account_id)
                elif crypto:  # portefeuille crypto sans aucun cours : son solde au registre
                    b.put(CRYPTO, NAMED, Decimal(v), account=ln.account_id)
                else:
                    b.put(CASH, CASH_KIND, Decimal(v), account=ln.account_id)
            elif ln.kind == "good":  # un bien hors comptes : ni secteur ni région, sa case
                if not holding:
                    b.put("Biens", NAMED, Decimal(v), account=ln.account_id)
            elif (isin := ln.asset[5:]) in comps:
                used.add(isin)
                assigned = Decimal(0)
                for bucket, w in comps[isin]:
                    assigned += w
                    if bucket == UNKNOWN and not holding:  # l'émetteur ne dit pas où
                        b.put(NOT_SPLIT, UNDETAILED, v * w, isin=isin)
                    else:
                        b.put(bucket, NAMED, v * w, isin=isin)
                if assigned < 1:
                    rest = OTHER_LINES if holding else NOT_SPLIT
                    b.put(rest, UNDETAILED, v * (1 - assigned), isin=isin)
            else:
                info = meta.get(isin, (isin, None, None, None, "other"))
                bucket, kind, est = classify(dimension, info, pack)
                b.put(bucket, kind, Decimal(v), isin=isin, estimated=est)
        return _result(b, s.currency, dimension, on_date, pack, owed, meta, accounts) | {
            "compositions_since": min((dates[i] for i in used), default=None),
            "unpriced": [
                {"isin": isin, "account_id": acc, "name": meta.get(isin, (isin,))[0]}
                for acc, isin in sorted(unpriced)
            ],
        }


def _result(
    b: _Buckets,
    ccy: str,
    dimension: str,
    on_date: str,
    pack: CountryPack,
    owed: int,
    meta: dict[str, Meta],
    accounts: dict[str, tuple[str, str]],
) -> dict[str, Any]:
    minor = {k: int(v.to_integral_value()) for k, v in b.value.items()}
    minor = {k: v for k, v in minor.items() if v > 0}
    total = int(sum(b.value.values(), Decimal(0)).to_integral_value())
    if not total:
        return _empty(dimension, on_date, ccy) | {"owed": Money(owed, ccy).to_api()}
    if minor and dimension != "holding":
        # les cases sont arrondies une à une : l'écart d'arrondi va à la plus grosse, pour que
        # leur somme soit le total au centime
        top = max(minor, key=lambda x: (minor[x], x))
        minor[top] += total - sum(minor.values())
    ranked = sorted(minor, key=lambda x: (_LAST.get(b.kind[x], 0), -minor[x], x))
    if dimension == "holding":
        named = [x for x in ranked if b.kind[x] == NAMED][:TOP]
        ranked = named + [x for x in ranked if b.kind[x] != NAMED]
    soft = Decimal(0)
    items = []
    for bucket in ranked:
        kind = b.kind[bucket]
        est = b.estimated.get(bucket, Decimal(0))
        soft += b.value[bucket] if kind in _LAST else est
        parts = sorted(b.parts[bucket].items(), key=lambda x: (-x[1], str(x[0])))
        items.append(
            {
                "bucket": bucket,
                "code": region_code(bucket, pack) if dimension == "region" else None,
                "kind": kind,
                "estimated": est * 2 > b.value[bucket],
                "value": Money(minor[bucket], ccy).to_api(),
                "weight": str((Decimal(minor[bucket]) / total).quantize(Decimal("0.0001"))),
                "count": sum(1 for _key, v in parts if v >= 1),
                "assets": [
                    {
                        "isin": isin,
                        "account_id": acc,
                        "name": meta.get(isin, (isin,))[0]
                        if isin
                        else accounts.get(acc or "", (acc or "",))[0],
                        "value": Money(int(v.to_integral_value()), ccy).to_api(),
                    }
                    for (isin, acc), v in parts[:ASSETS_PER_BUCKET]
                    if v >= 1
                ],
            }
        )
    covered = str((1 - soft / Decimal(total)).quantize(Decimal("0.0001")))
    return {
        "dimension": dimension,
        "on_date": on_date,
        "currency": ccy,
        "total": Money(total, ccy).to_api(),
        "owed": Money(owed, ccy).to_api(),
        "covered": covered,
        "items": items,
    }
