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

Une décision vient d'une proposition (`decide_break`, break_kinds.py) ; elle se retire par une
ligne de `reconcile_withdrawals` (migration 0021), jamais par un effacement, et la lecture
l'ignore alors.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import Connection, text

from hub.core.errors import Problem
from hub.kernel.clock import now_iso
from hub.kernel.ids import new_id

KINDS = ("unexplained", "sent_outside", "arrived_outside", "no_price", "stale_price", "stale_fx")
DECISIONS = {
    "unexplained": ("cost", "accept"),
    "sent_outside": ("gone", "accept"),
    "arrived_outside": ("accept",),
    "no_price": ("accept",),
    "stale_price": ("accept",),
    "stale_fx": ("accept",),
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
    proposal_id: str | None = None

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
            "proposal_id": self.proposal_id,
        }


_COLUMNS = (
    "d.id, d.account_id, d.asset, d.break_kind, d.decision, d.on_date, d.quantity, "
    "d.cost_minor, d.currency, d.note, d.created_at, d.proposal_id"
)
_LIVE = (
    "FROM reconcile_decisions d LEFT JOIN reconcile_withdrawals w ON w.decision_id = d.id "
    "WHERE w.decision_id IS NULL"
)


def _decision(r: tuple[object, ...]) -> Decision:
    return Decision(
        str(r[0]),
        str(r[1]),
        str(r[2]),
        str(r[3]),
        str(r[4]),
        str(r[5]),
        None if r[6] is None else Decimal(str(r[6])),
        None if r[7] is None else int(str(r[7])),
        str(r[8]),
        None if r[9] is None else str(r[9]),
        str(r[10]),
        None if r[11] is None else str(r[11]),
    )


def read(conn: Connection) -> list[Decision]:
    """Les décisions en vigueur (pas les retirées), de la plus ancienne à la plus récente."""
    rows = conn.execute(text(f"SELECT {_COLUMNS} {_LIVE} ORDER BY d.created_at, d.id")).fetchall()
    return [_decision(tuple(r)) for r in rows]


def get(conn: Connection, decision_id: str) -> Decision | None:
    """Une décision en vigueur ; None si inconnue ou retirée."""
    row = conn.execute(
        text(f"SELECT {_COLUMNS} {_LIVE} AND d.id = :i"),
        {"i": decision_id},
    ).first()
    return None if row is None else _decision(tuple(row))


def withdraw(conn: Connection, decision_id: str, *, proposal_id: str | None, actor: str) -> None:
    """Retire une décision : une ligne de retrait, la décision reste lisible dans l'historique."""
    if get(conn, decision_id) is None:
        raise Problem("not_found", "décision inconnue ou déjà retirée")
    conn.execute(
        text(
            "INSERT INTO reconcile_withdrawals (decision_id, proposal_id, created_at, actor) "
            "VALUES (:i, :p, :at, :a)"
        ),
        {"i": decision_id, "p": proposal_id, "at": now_iso(), "a": actor},
    )


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
    proposal_id: str | None = None,
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
        proposal_id,
    )
    conn.execute(
        text(
            "INSERT INTO reconcile_decisions (id, account_id, asset, break_kind, decision, "
            "on_date, quantity, cost_minor, currency, note, created_at, actor, proposal_id) "
            "VALUES (:id, :a, :s, :k, :d, :on, :q, :c, :ccy, :n, :at, :actor, :p)"
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
            "p": proposal_id,
        },
    )
    return d
