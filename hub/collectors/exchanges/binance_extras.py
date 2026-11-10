"""Distributions et petits soldes Binance (`asset/assetDividend`, `asset/dribblet`), deux flux
de l'historique (binance_history.py)."""

from __future__ import annotations

from hub.collectors.base import Failure
from hub.collectors.exchanges.binance_api import Api, Op, _day, _qty, _rows

# les intérêts Simple Earn viennent de `rewards` : pas deux fois
_EARN_INFO = ("simple earn", "flexible", "locked")
# une crypto renommée (nouveau nom → ancien) : Binance rend le nouveau jeton par une
# distribution « Token Swap » et retire l'ancien sans l'écrire
RENAMED = {"RENDER": "RNDR", "POL": "MATIC"}


def dividends(api: Api, start: int, end: int) -> list[Op]:
    out = []
    path, step = "/sapi/v1/asset/assetDividend", "binance.dividends"
    for r in api.windows(path, step, start, end, 89, _rows, limit=500, params={"limit": 500}):
        info = str(r.get("enInfo") or "")
        if any(k in info.lower() for k in _EARN_INFO):
            continue
        op = Op(f"dividend:{r.get('tranId') or r['id']}", "distribution", _day(r["divTime"]))
        asset, quantity = str(r["asset"]).upper(), _qty(r["amount"])
        if "swap" in info.lower() and asset in RENAMED:
            # l'échange de l'ancien jeton contre le nouveau, part pour part : pas un revenu
            op.kind = "trade"
            out.append(op.leg(asset, quantity, "trade").leg(RENAMED[asset], -quantity, "trade"))
            continue
        out.append(op.leg(asset, quantity, "income"))
    return out


def dust(api: Api, start: int) -> list[Op]:
    """Petits soldes convertis en BNB (les 100 dernières conversions, que l'API garde)."""
    doc = api.get("/sapi/v1/asset/dribblet", "binance.dust", {})
    if doc is None:
        api.gaps["binance.dust"].append((start, 0))
        return []
    groups = doc.get("userAssetDribblets") if isinstance(doc, dict) else None
    if not isinstance(groups, list):
        raise Failure("invalid_file", "binance.dust")
    out = []
    for g in groups:
        if int(g["operateTime"]) < start:
            continue
        op = Op(f"dust:{g['transId']}", "dust", _day(g["operateTime"]))
        for d in g.get("userAssetDribbletDetails") or []:
            fee = _qty(d.get("serviceChargeAmount") or 0)
            op.leg(d["fromAsset"], -_qty(d["amount"]), "trade")
            op.leg("BNB", _qty(d["transferedAmount"]) + fee, "trade").leg("BNB", -fee, "fee")
        out.append(op)
    return out
