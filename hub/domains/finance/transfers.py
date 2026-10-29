"""Virements appariés (lot 6) : les deux côtés d'un virement entre mes comptes.

Un débit d'un compte et un crédit d'un autre compte du registre sont appariés quand ils ont la
même devise, le même montant au centime et au plus `WINDOW_DAYS` jours d'écart, et que l'on
sait que c'est un virement, par ordre de confiance :

1. `iban` : l'IBAN de contrepartie de l'un est celui de l'autre compte ;
2. `code` : les deux côtés ressemblent à un virement (catégorie de virement ou d'épargne,
   IBAN de contrepartie qui est l'un de mes comptes, versement VIAC ou IBKR) ;
3. `amount` : c'est le seul candidat de ce montant dans la fenêtre, et soit un côté ressemble à
   un virement (une recharge Revolut depuis la BCF, par exemple), soit les deux comptes sont chez
   le même établissement à un jour d'écart au plus (le compte Revolut et ses poches, dont les
   mouvements n'ont ni IBAN ni code de virement).

Un mouvement crypto relié à l'import à l'autre côté (`peer`, même txId ou même quantité) passe
avant tout le reste. Chaque écriture n'a qu'un seul partenaire. La table est dérivée :
recalculée en entier avec les instantanés. Une écriture appariée sans catégorie compte comme un
virement entre mes comptes dans le budget (vue `v_entry_allocation`) ; une catégorie posée
reste la sienne.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import Connection, text

from hub.domains.finance import institutions
from hub.domains.finance.reads import money
from hub.kernel.clock import now_iso

WINDOW_DAYS = 5
SIBLING_DAYS = 1  # compte et poche du même établissement : le virement est passé le jour même
TRANSFER_CODES = institutions.prefixes(transfer=True)
_INTERNAL = institutions.like_any("e.bank_tx_code", institutions.prefixes(internal=True))
METHOD_RANK = {"iban": 0, "code": 1, "amount": 2}


@dataclass(frozen=True)
class Move:
    seq: int
    id: str
    account_id: str
    account_iban: str | None
    institution: str | None
    on: date
    amount: int
    currency: str
    counterparty_iban: str | None
    code: str
    group: str | None  # groupe de la catégorie courante
    peer: int | None = None  # l'autre côté relevé à l'import (mouvement crypto : `links`)

    def transfer_like(self, own: frozenset[str]) -> bool:
        return (
            self.group in ("transfer", "savings")
            or (self.counterparty_iban is not None and self.counterparty_iban in own)
            or self.code.startswith(TRANSFER_CODES)
        )


@dataclass(frozen=True)
class Link:
    debit: Move
    credit: Move
    method: str
    explicit: bool = False  # relié à l'import (même txId ou même quantité) : avant tout le reste

    @property
    def days(self) -> int:
        return abs((self.credit.on - self.debit.on).days)


def _moves(conn: Connection) -> list[Move]:
    rows = conn.execute(
        text(
            "SELECT e.seq, e.id, e.account_id, a.iban, a.institution, e.booking_date, "  # noqa: S608 - codes déclarés
            "e.amount_minor, e.currency, "
            "e.counterparty_iban, coalesce(e.bank_tx_code, ''), c.grp, "
            "CAST(json_extract(e.fx_json, '$.peer') AS INTEGER) "
            "FROM entries e JOIN accounts a ON a.id = e.account_id "
            "LEFT JOIN v_entry_category vc ON vc.entry_seq = e.seq "
            "LEFT JOIN categories c ON c.id = vc.category_id "
            "WHERE e.kind = 'movement' AND e.amount_minor != 0 "
            f"AND (e.bank_tx_code IS NULL OR NOT ({_INTERNAL}))"
        )
    ).fetchall()
    return [
        Move(
            int(r[0]),
            r[1],
            r[2],
            r[3],
            r[4],
            date.fromisoformat(r[5]),
            int(r[6]),
            r[7],
            r[8],
            r[9],
            r[10],
            int(r[11]) if r[11] is not None else None,
        )
        for r in rows
    ]


def _siblings(d: Move, c: Move) -> bool:
    return bool(d.institution) and d.institution == c.institution


def _close(a: Move, b: Move) -> bool:
    return _siblings(a, b) and abs((a.on - b.on).days) <= SIBLING_DAYS


def _sibling_pair(
    d: Move, c: Move, near: list[Move], debits: dict[tuple[str, int], list[Move]]
) -> bool:
    """Compte et poche du même établissement : seuls candidats l'un pour l'autre parmi les
    comptes de cet établissement, à un jour près. Un mouvement ailleurs (la BCF qui vient de
    recharger le compte du même montant) ne les rend pas ambigus."""
    if not _close(d, c):
        return False
    if any(x.seq != c.seq and _close(d, x) for x in near):
        return False
    return not any(
        x.seq != d.seq and x.account_id != c.account_id and _close(x, c)
        for x in debits[(d.currency, d.amount)]
    )


def match(moves: list[Move], own: frozenset[str]) -> list[Link]:
    credits: dict[tuple[str, int], list[Move]] = defaultdict(list)
    debits: dict[tuple[str, int], list[Move]] = defaultdict(list)
    for m in moves:
        (credits if m.amount > 0 else debits)[(m.currency, m.amount)].append(m)
    near_of: dict[int, list[Move]] = {}
    for d in moves:
        if d.amount < 0:
            near_of[d.seq] = [
                c
                for c in credits.get((d.currency, -d.amount), [])
                if c.account_id != d.account_id and abs((c.on - d.on).days) <= WINDOW_DAYS
            ]
    # compte et poche d'abord : un mouvement qu'ils expliquent ne rend pas un autre ambigu
    # (BCF → compte Revolut → poche, le même montant le même jour)
    candidates = [
        Link(d, c, "amount")
        for d in moves
        if d.amount < 0
        for c in near_of[d.seq]
        if _sibling_pair(d, c, near_of[d.seq], debits)
    ]
    explained = {x.debit.seq for x in candidates} | {x.credit.seq for x in candidates}
    for d in moves:
        if d.amount >= 0:
            continue
        near = near_of[d.seq]
        open_near = [c for c in near if c.seq not in explained]
        for c in near:
            if (d.counterparty_iban and d.counterparty_iban == c.account_iban) or (
                c.counterparty_iban and c.counterparty_iban == d.account_iban
            ):
                candidates.append(Link(d, c, "iban"))
            elif d.transfer_like(own) and c.transfer_like(own):
                candidates.append(Link(d, c, "code"))
            elif (
                open_near == [c]
                and d.seq not in explained
                and (d.transfer_like(own) or c.transfer_like(own))
            ):
                rivals = [
                    x
                    for x in debits[(d.currency, d.amount)]
                    if x.seq != d.seq
                    and x.seq not in explained
                    and abs((x.on - c.on).days) <= WINDOW_DAYS
                ]
                if not rivals:
                    candidates.append(Link(d, c, "amount"))
    by_seq = {m.seq: m for m in moves}
    for m in moves:
        other = by_seq.get(m.peer) if m.peer is not None else None
        if other is not None and other.amount == -m.amount and other.account_id != m.account_id:
            d, c = (m, other) if m.amount < 0 else (other, m)
            candidates.append(Link(d, c, "code", explicit=True))
    candidates.sort(
        key=lambda x: (not x.explicit, METHOD_RANK[x.method], x.days, x.debit.seq, x.credit.seq)
    )
    used: set[int] = set()
    out = []
    for link in candidates:
        if link.debit.seq in used or link.credit.seq in used:
            continue
        used |= {link.debit.seq, link.credit.seq}
        out.append(link)
    return out


def refresh(conn: Connection) -> int:
    """Recalcule toute la table dans la transaction de l'appelant ; renvoie le nombre de paires."""
    own = frozenset(
        str(r[0]) for r in conn.execute(text("SELECT iban FROM accounts WHERE iban IS NOT NULL"))
    )
    links = match(_moves(conn), own)
    at = now_iso()
    conn.execute(text("DELETE FROM transfer_links"))
    if links:
        conn.execute(
            text(
                "INSERT INTO transfer_links (debit_seq, credit_seq, method, days, computed_at) "
                "VALUES (:d, :c, :m, :n, :at)"
            ),
            [
                {"d": x.debit.seq, "c": x.credit.seq, "m": x.method, "n": x.days, "at": at}
                for x in links
            ],
        )
    return len(links)


def peer(conn: Connection, entry_seq: int) -> dict[str, Any] | None:
    """L'autre côté d'une écriture appariée : identifiant, compte, date."""
    row = conn.execute(
        text(
            "SELECT e.id, e.account_id, a.name, e.booking_date, l.method FROM transfer_links l "
            "JOIN entries e ON e.seq = CASE WHEN l.debit_seq = :s THEN l.credit_seq "
            "ELSE l.debit_seq END JOIN accounts a ON a.id = e.account_id "
            "WHERE l.debit_seq = :s OR l.credit_seq = :s"
        ),
        {"s": entry_seq},
    ).first()
    if row is None:
        return None
    return {"id": row[0], "account_id": row[1], "account": row[2], "date": row[3], "method": row[4]}


def summary(conn: Connection, *, detailed: bool) -> dict[str, Any]:
    """Paires par méthode et virements sans autre côté (catégorie de virement, IBAN de
    contrepartie qui est l'un de mes comptes). `detailed` : la liste des orphelins."""
    by_method = {
        r[0]: int(r[1])
        for r in conn.execute(text("SELECT method, count(*) FROM transfer_links GROUP BY method"))
    }
    orphans = conn.execute(
        text(
            "SELECT e.id, e.account_id, a.name, e.booking_date, e.amount_minor, e.currency "
            "FROM entries e JOIN accounts a ON a.id = e.account_id "
            "JOIN v_entry_category vc ON vc.entry_seq = e.seq "
            "WHERE e.kind = 'movement' AND vc.category_id = 'transfer-own' "
            "AND e.counterparty_iban IN (SELECT iban FROM accounts WHERE iban IS NOT NULL) "
            "AND e.seq NOT IN (SELECT debit_seq FROM transfer_links) "
            "AND e.seq NOT IN (SELECT credit_seq FROM transfer_links) "
            "ORDER BY e.booking_date DESC LIMIT 100"
        )
    ).fetchall()
    out: dict[str, Any] = {
        "pairs": sum(by_method.values()),
        "by_method": by_method,
        "unmatched": len(orphans),
    }
    if detailed:
        out["unmatched_items"] = [
            {
                "id": r[0],
                "account_id": r[1],
                "account": r[2],
                "date": r[3],
                "amount": money(r[4], r[5]),
            }
            for r in orphans
        ]
    return out
