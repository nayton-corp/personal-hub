"""Contrôle des chiffres du patrimoine pour `hub verify` (docs/finance-politique.md, « Contrôles »).

- Les ruptures du rapprochement (reconcile.py) : comptées et chiffrées, avec la part des
  placements expliquée et cotée. Une rupture ouverte n'est pas une faute du hub : elle attend ta
  décision ou un import, et le contrôle la montre sans échouer.
- Un seul gain : la performance « Max » des cryptos et leur résultat depuis l'achat
  (crypto_cost.py) s'accordent, à la tolérance par ligne près, plus ce que les ruptures ouvertes
  laissent hors du résultat. Au-delà, le contrôle échoue : un des deux calculs se trompe.
- Les relevés à valeur 0 pour des parts tenues (SwissBorg) : comptés, jamais pris comme valeur.

Des agrégats seulement.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Connection, text

from hub.domains.finance.patrimoine.app import crypto_cost, perf_lines, performance, reconcile
from hub.domains.finance.patrimoine.app import valuation as val
from hub.domains.finance.registre.model.amounts import money
from hub.kernel.money import base_currency


def crypto_gap(conn: Connection, on: str) -> tuple[int, int] | None:
    """(performance « Max », résultat depuis l'achat) des cryptos, en centimes, ou None."""
    eng = perf_lines.build(conn, on)
    crypto = set(conn.execute(text("SELECT id FROM accounts WHERE kind = 'crypto'")).scalars())
    res = crypto_cost.result(conn, on, val.Positions(conn))
    if eng is None or not crypto or res is None:
        return None
    ids = [i for i, ln in eng.lines.items() if ln.kind == "position" and ln.account_id in crypto]
    if not ids:
        return None
    gain = performance.report(eng, ids, None, None, "month")["summary"]["gain"]["minor"]
    return int(gain), int(res["result"]["minor"])


def figures(conn: Connection, on: str) -> tuple[bool, dict[str, Any]]:
    ccy = base_currency()
    rep = reconcile.report(conn, on)
    crypto = set(conn.execute(text("SELECT id FROM accounts WHERE kind = 'crypto'")).scalars())
    out_of_result = sum(abs(b.value or 0) for b in rep.breaks if b.account_id in crypto)
    lines = len({(b.account_id, b.asset) for b in rep.breaks})
    zero = conn.execute(
        text("SELECT count(*) FROM holdings WHERE value_minor = 0 AND CAST(quantity AS REAL) > 0")
    ).scalar_one()
    detail: dict[str, Any] = {
        "breaks": len(rep.breaks),
        "breaks_value": money(sum(abs(b.value or 0) for b in rep.breaks), ccy),
        "by_kind": {
            k: sum(1 for b in rep.breaks if b.kind == k)
            for k in sorted({b.kind for b in rep.breaks})
        },
        "completeness": rep.public({})["completeness"],
        "zero_value_reports_ignored": int(zero),
    }
    ok = True
    gap = crypto_gap(conn, on)
    if gap is not None:
        max_gain, since_purchase = gap
        allowed = rep.tolerance_minor * (1 + lines) + out_of_result
        ok = abs(max_gain - since_purchase) <= allowed
        detail["crypto"] = {
            "performance_max": money(max_gain, ccy),
            "since_purchase": money(since_purchase, ccy),
            "allowed_gap": money(allowed, ccy),
            "ok": ok,
        }
    return ok, detail
