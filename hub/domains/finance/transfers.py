"""Virements appariés (lot 6) : les deux côtés d'un virement entre mes comptes.

Un débit d'un compte et un crédit d'un autre compte du registre sont appariés quand ils ont la
même devise, le même montant au centime et au plus `WINDOW_DAYS` jours d'écart, et que l'on
sait que c'est un virement, par ordre de confiance :

1. `iban` : l'IBAN de contrepartie de l'un est celui de l'autre compte ;
2. `code` : les deux côtés ressemblent à un virement (catégorie de virement ou d'épargne,
   IBAN de contrepartie qui est l'un de mes comptes, versement VIAC ou IBKR) ;
3. `amount` : un seul côté y ressemble, et c'est le seul candidat de ce montant dans la fenêtre
   (une recharge Revolut depuis la BCF, par exemple).

Chaque écriture n'a qu'un seul partenaire. La table est dérivée : recalculée en entier avec les
instantanés. Une écriture appariée sans catégorie compte comme un virement entre mes comptes
dans le budget (vue `v_entry_allocation`) ; une catégorie posée reste la sienne.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import Connection, text

from hub.core.clock import now_iso
from hub.domains.finance import institutions
from hub.domains.finance.reads import money

WINDOW_DAYS = 5
TRANSFER_CODES = institutions.prefixes(transfer=True)
_INTERNAL = institutions.like_any("e.bank_tx_code", institutions.prefixes(internal=True))
METHOD_RANK = {"iban": 0, "code": 1, "amount": 2}


@dataclass(frozen=True)
class Move:
    seq: int
    id: str
    account_id: str
    account_iban: str | None
    on: date
    amount: int
    currency: str
    counterparty_iban: str | None
    code: str
    group: str | None  # groupe de la catégorie courante

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

    @property
    def days(self) -> int:
        return abs((self.credit.on - self.debit.on).days)


def _moves(conn: Connection) -> list[Move]:
    rows = conn.execute(
        text(
            "SELECT e.seq, e.id, e.account_id, a.iban, e.booking_date, e.amount_minor, e.currency, "  # noqa: S608 - codes déclarés
            "e.counterparty_iban, coalesce(e.bank_tx_code, ''), c.grp "
            "FROM entries e JOIN accounts a ON a.id = e.account_id "
            "LEFT JOIN v_entry_category vc ON vc.entry_seq = e.seq "
            "LEFT JOIN categories c ON c.id = vc.category_id "
            "WHERE e.kind = 'movement' AND e.amount_minor != 0 "
            f"AND (e.bank_tx_code IS NULL OR NOT ({_INTERNAL}))"
        )
    ).fetchall()
    return [
        Move(
            int(r[0]), r[1], r[2], r[3], date.fromisoformat(r[4]), int(r[5]), r[6], r[7], r[8], r[9]
        )
        for r in rows
    ]


def match(moves: list[Move], own: frozenset[str]) -> list[Link]:
    credits: dict[tuple[str, int], list[Move]] = defaultdict(list)
    debits: dict[tuple[str, int], list[Move]] = defaultdict(list)
    for m in moves:
        (credits if m.amount > 0 else debits)[(m.currency, m.amount)].append(m)
    candidates: list[Link] = []
    for d in moves:
        if d.amount >= 0:
            continue
        near = [
            c
            for c in credits.get((d.currency, -d.amount), [])
            if c.account_id != d.account_id and abs((c.on - d.on).days) <= WINDOW_DAYS
        ]
        for c in near:
            if (d.counterparty_iban and d.counterparty_iban == c.account_iban) or (
                c.counterparty_iban and c.counterparty_iban == d.account_iban
            ):
                candidates.append(Link(d, c, "iban"))
            elif d.transfer_like(own) and c.transfer_like(own):
                candidates.append(Link(d, c, "code"))
            elif (d.transfer_like(own) or c.transfer_like(own)) and len(near) == 1:
                rivals = [
                    x
                    for x in debits[(d.currency, d.amount)]
                    if x.seq != d.seq and abs((x.on - c.on).days) <= WINDOW_DAYS
                ]
                if not rivals:
                    candidates.append(Link(d, c, "amount"))
    candidates.sort(key=lambda x: (METHOD_RANK[x.method], x.days, x.debit.seq, x.credit.seq))
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
