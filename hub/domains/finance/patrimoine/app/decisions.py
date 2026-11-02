"""Tes décisions sur les ruptures du rapprochement (table `reconcile_decisions`, migration 0020 ;
docs/finance-politique.md).

Une rupture se recalcule à chaque lecture (reconcile.py) ; seule la décision se garde :

- `cost` (parts sans historique) : un lot de parts entré à son prix de revient saisi, le jour où
  les parts sont apparues ;
- `accept` (parts sans historique) : un lot entré à sa valeur du jour d'apparition, gardée au
  moment de la décision ; pour une sortie non vue, un envoi, une arrivée, un cours : rien ne
  change dans les calculs, la rupture sort de la liste ;
- `gone` (envoi vers l'extérieur) : marqué « parti », la sortie reste au coût.

Les lots entrent dans le prix de revient (crypto_cost.py) et dans la performance (perf_lines.py)
comme une opération de plus : ils expliquent les parts, qui ne repartent pas au cours du jour.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import Connection, text

from hub.core.errors import Problem
from hub.kernel.clock import now_iso
from hub.kernel.ids import new_id

KINDS = ("unexplained", "sent_outside", "arrived_outside", "no_price", "stale_price")
DECISIONS = {
    "unexplained": ("cost", "accept"),
    "sent_outside": ("gone", "accept"),
    "arrived_outside": ("accept",),
    "no_price": ("accept",),
    "stale_price": ("accept",),
}


@dataclass(frozen=True)
class Decision:
    id: str
    account_id: str
    asset: str
    break_kind: str
    decision: str
    on_date: str
    quantity: Decimal | None
    cost_minor: int | None
    currency: str
    note: str | None
    created_at: str

    def public(self) -> dict[str, object]:
        return {
            "id": self.id,
            "account_id": self.account_id,
            "asset": self.asset,
            "break_kind": self.break_kind,
            "decision": self.decision,
            "on_date": self.on_date,
            "quantity": None if self.quantity is None else str(self.quantity),
            "cost_minor": self.cost_minor,
            "currency": self.currency,
            "note": self.note,
            "created_at": self.created_at,
        }


def read(conn: Connection) -> list[Decision]:
    rows = conn.execute(
        text(
            "SELECT id, account_id, asset, break_kind, decision, on_date, quantity, cost_minor, "
            "currency, note, created_at FROM reconcile_decisions ORDER BY created_at, id"
        )
    ).fetchall()
    return [
        Decision(
            r[0],
            r[1],
            r[2],
            r[3],
            r[4],
            r[5],
            None if r[6] is None else Decimal(r[6]),
            None if r[7] is None else int(r[7]),
            r[8],
            r[9],
            r[10],
        )
        for r in rows
    ]


Lot = tuple[str, str, int, str, Decimal, bool, str]  # comme une jambe de crypto_cost._legs


def lots(found: list[Decision]) -> list[Lot]:
    """Les parts sans historique que tes décisions expliquent : (jour, rôle, coût en centimes,
    symbole, parts, interne, compte), triés par jour."""
    out: list[Lot] = []
    for d in found:
        if d.break_kind != "unexplained" or d.decision not in ("cost", "accept"):
            continue
        if d.quantity is None or d.quantity <= 0 or d.cost_minor is None:
            continue
        symbol = d.asset.split(":", 1)[1] if d.asset.startswith("CRYPTO:") else d.asset
        role = "trade" if d.decision == "cost" else "in"
        out.append((d.on_date, role, d.cost_minor, symbol, d.quantity, False, d.account_id))
    return sorted(out, key=lambda x: x[0])


def add(
    conn: Connection,
    *,
    account_id: str,
    asset: str,
    break_kind: str,
    decision: str,
    on_date: str,
    quantity: Decimal | None,
    cost_minor: int | None,
    currency: str,
    note: str | None,
    actor: str,
) -> Decision:
    if decision not in DECISIONS.get(break_kind, ()):
        raise Problem("validation.params", f"{decision} ne règle pas une rupture {break_kind}")
    if decision == "cost" and (cost_minor is None or quantity is None or quantity <= 0):
        raise Problem("validation.params", "un coût saisi demande des parts et un montant")
    if (
        conn.execute(text("SELECT 1 FROM accounts WHERE id = :a"), {"a": account_id}).first()
        is None
    ):
        raise Problem("not_found", "compte inconnu")
    d = Decision(
        new_id(),
        account_id,
        asset,
        break_kind,
        decision,
        on_date,
        quantity,
        cost_minor,
        currency,
        note,
        now_iso(),
    )
    conn.execute(
        text(
            "INSERT INTO reconcile_decisions (id, account_id, asset, break_kind, decision, "
            "on_date, quantity, cost_minor, currency, note, created_at, actor) VALUES "
            "(:id, :a, :s, :k, :d, :on, :q, :c, :ccy, :n, :at, :actor)"
        ),
        {
            "id": d.id,
            "a": account_id,
            "s": asset,
            "k": break_kind,
            "d": decision,
            "on": on_date,
            "q": None if quantity is None else format(quantity.normalize(), "f"),
            "c": cost_minor,
            "ccy": currency,
            "n": note,
            "at": d.created_at,
            "actor": actor,
        },
    )
    return d
