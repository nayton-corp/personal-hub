"""Mes placements depuis l'achat : un seul gain par classe (docs/finance-politique.md).

- Cryptos : le résultat depuis l'achat (crypto_cost.py), latent plus réalisé, en francs et en
  dollars ; c'est aussi la performance « Max » de leurs lignes.
- Titres (IBKR, actions) : la performance « Max » des positions, dont les achats et ventes sont
  des flux au prix payé, plus les dividendes et moins les frais du compte.
- 3e pilier (VIAC) : la valeur moins les versements nets.

Les comptes de liquidités n'ont pas de prix d'achat : ils n'entrent pas ici. Les ruptures ouvertes
(reconcile.py) disent la part de la valeur que le calcul ne sait pas encore expliquer. Des
agrégats seulement.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Connection, text

from hub.domains.finance.patrimoine.app import crypto_cost, perf_lines, performance, reconcile
from hub.domains.finance.patrimoine.app import valuation as val
from hub.domains.finance.registre.model.amounts import money
from hub.kernel.money import base_currency


def _pension(conn: Connection, ids: list[str], on: str, fx: val.FxTable) -> tuple[int, int]:
    """(valeur, versements nets) des comptes de prévoyance, en centimes de la devise de base."""
    if not ids:
        return 0, 0
    value = deposits = 0
    positions = val.Positions(conn, fx)
    for acc in ids:
        sql = text("SELECT currency FROM accounts WHERE id = :a")
        ccy = str(conn.execute(sql, {"a": acc}).scalar_one())
        row = conn.execute(
            text(
                f"SELECT sum(e.amount_minor), {val.DEPOSITS_SQL} FROM entries e "  # noqa: S608
                f"{val.CATEGORY_JOIN} WHERE e.account_id = :a AND e.booking_date <= :d"
            ),
            {"a": acc, "d": on},
        ).one()
        balance, paid = int(row[0] or 0), int(row[1] or 0)
        held, held_ccy, _missing = val.held(positions, acc, ccy, balance, on)
        value += fx.to_base(held, held_ccy, on) or 0
        deposits += fx.to_base(paid, ccy, on) or 0
    return value, deposits


def summary(conn: Connection, on: str) -> dict[str, Any]:
    ccy = base_currency()
    accts = conn.execute(text("SELECT id, kind FROM accounts WHERE hidden = 0")).fetchall()
    by_kind: dict[str, list[str]] = {}
    for acc, kind in accts:
        by_kind.setdefault(str(kind), []).append(str(acc))
    fx = val.FxTable(conn)
    classes: list[dict[str, Any]] = []
    crypto = (
        crypto_cost.result(conn, on, val.Positions(conn, fx)) if by_kind.get("crypto") else None
    )
    if crypto is not None:
        classes.append(
            {
                "kind": "crypto",
                "value": crypto["value"],
                "result": crypto["result"],
                "cost": crypto["cost"],
                "realized": crypto["realized"],
                "income": crypto["income"],
                "result_usd": crypto["result_usd"],
                "unknown_cost_value": crypto["unknown_cost_value"],
            }
        )
    securities = by_kind.get("securities", [])
    eng = perf_lines.engine_for(conn, on) if securities else None
    if eng is not None:
        ids = [i for i, ln in eng.lines.items() if ln.account_id in securities]
        positions = [i for i in ids if eng.lines[i].kind == "position"]
        if positions:
            rep = performance.report(eng, ids, None, None, "month")["summary"]
            pos = performance.report(eng, positions, None, None, "month")["summary"]
            income, fees = int(rep["income"]["minor"]), int(rep["fees"]["minor"])
            gain = int(pos["gain"]["minor"])
            classes.append(
                {
                    "kind": "securities",
                    "value": pos["end"],
                    "result": money(gain + income + fees, ccy),
                    "unrealized": money(gain, ccy),
                    "income": money(income, ccy),
                    "fees": money(fees, ccy),
                }
            )
    value, deposits = _pension(conn, by_kind.get("pension", []), on, fx)
    if value or deposits:
        classes.append(
            {
                "kind": "pension",
                "value": money(value, ccy),
                "deposits": money(deposits, ccy),
                "result": money(value - deposits, ccy),
            }
        )
    rep_breaks = reconcile.report(conn, on).public(reconcile.names(conn))
    total = sum(int(c["result"]["minor"]) for c in classes)
    worth = sum(int(c["value"]["minor"]) for c in classes)
    return {
        "on_date": on,
        "currency": ccy,
        "classes": classes,
        "result": money(total, ccy),
        "value": money(worth, ccy),
        "completeness": rep_breaks["completeness"],
        "breaks": rep_breaks["count"],
        "breaks_value": rep_breaks["open_value"],
    }
