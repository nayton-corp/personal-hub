"""Le modèle canonique des mouvements crypto (audit C1) : la jambe crypto d'une écriture
(`crypto_moves` : rôle, actif, parts, txid), écrite une fois par la source, et son lien
(`crypto_links`) : l'autre côté d'un virement entre mes comptes, ou une mise ou sortie de staking
(les parts restent à moi). Un lien s'écrit à l'import (même txid, même quantité, marque de la
source) ou par une proposition validée (`link_crypto_moves`, crypto_pairing.py) ; il se retire par
une ligne de retrait. Rien n'est deviné à la lecture : le prix de revient (crypto_cost.py), le
rapprochement (reconcile.py) et les virements (transfers.py) lisent ces tables.

Rôles : `trade` (achat, vente, conversion), `income` (récompense), `fee`, `in` (arrivée ou dépôt),
`out` (envoi ou retrait).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import Connection, text

from hub.core.errors import Problem
from hub.domains.finance.patrimoine.model import instruments
from hub.kernel.clock import now_iso
from hub.kernel.ids import new_id

ROLES = ("trade", "income", "fee", "in", "out")
KINDS = ("transfer", "stake")
METHODS = ("txid", "quantity", "source", "window", "claim")
# lien actif : sans ligne de retrait
ACTIVE = (
    "SELECT l.id, l.entry_seq, l.kind, l.peer_seq FROM crypto_links l "
    "LEFT JOIN crypto_link_withdrawals w ON w.link_id = l.id WHERE w.link_id IS NULL"
)


def role(code: str | None) -> str | None:
    """Rôle d'une écriture crypto d'après son code (EXCHANGE/…, SWISSBORG/…, CRYPTO/…)."""
    c = code or ""
    if "/TRADE" in c:
        return "trade"
    if "/INCOME" in c:
        return "income"
    if "/FEE" in c:
        return "fee"
    if c.endswith("/DEPOSIT") or c == "CRYPTO/RECEIVE":
        return "in"
    if c.endswith("/WITHDRAWAL") or c == "CRYPTO/SEND":
        return "out"
    return None


def record(
    conn: Connection,
    entry_seq: int,
    code: str,
    asset: str,
    quantity: Decimal,
    *,
    txid: str | None = None,
    address: str | None = None,
    network: str | None = None,
    usd: str | None = None,
    created_at: str,
) -> None:
    """La jambe crypto d'une écriture qui vient d'être ajoutée au registre."""
    found = role(code)
    if found is None:
        raise Problem("validation.params", f"code sans rôle crypto : {code}")
    conn.execute(
        text(
            "INSERT INTO crypto_moves (entry_seq, role, asset, quantity, txid, address, network, "
            "usd, created_at) VALUES (:seq, :r, :a, :q, :t, :ad, :n, :u, :at)"
        ),
        {
            "seq": entry_seq,
            "r": found,
            "a": asset.upper(),
            "q": instruments.qty_text(quantity),
            "t": txid or None,
            "ad": address or None,
            "n": network or None,
            "u": usd,
            "at": created_at,
        },
    )


def link(
    conn: Connection,
    entry_seq: int,
    kind: str,
    peer_seq: int | None,
    method: str,
    *,
    actor: str,
    proposal_id: str | None = None,
    created_at: str | None = None,
) -> str:
    """L'autre côté d'un mouvement (`transfer` : `peer_seq` est l'écriture de l'autre compte ;
    `stake` : `peer_seq` est le claim qui a révélé la sortie, ou rien)."""
    if kind not in KINDS or method not in METHODS:
        raise Problem("validation.params", "lien crypto illisible")
    if kind == "transfer" and peer_seq is None:
        raise Problem("validation.params", "un virement a un autre côté")
    link_id = new_id()
    conn.execute(
        text(
            "INSERT INTO crypto_links (id, entry_seq, kind, peer_seq, method, proposal_id, "
            "created_at, actor) VALUES (:id, :e, :k, :p, :m, :pr, :at, :actor)"
        ),
        {
            "id": link_id,
            "e": entry_seq,
            "k": kind,
            "p": peer_seq,
            "m": method,
            "pr": proposal_id,
            "at": created_at or now_iso(),
            "actor": actor,
        },
    )
    return link_id


def withdraw(conn: Connection, link_id: str, *, actor: str, proposal_id: str | None) -> None:
    if conn.execute(text(f"{ACTIVE} AND l.id = :id"), {"id": link_id}).first() is None:
        raise Problem("not_found", "lien inconnu ou déjà retiré")
    conn.execute(
        text(
            "INSERT INTO crypto_link_withdrawals (link_id, proposal_id, created_at, actor) "
            "VALUES (:id, :p, :at, :actor)"
        ),
        {"id": link_id, "p": proposal_id, "at": now_iso(), "actor": actor},
    )


def linked(conn: Connection, entry_seq: int, *, as_peer: bool = False) -> bool:
    """Un mouvement déjà relié (d'un côté ou de l'autre) ne se relie pas deux fois ; `as_peer` :
    seulement comme autre côté (un claim porte déjà son lien de staking)."""
    where = "l.peer_seq = :s" if as_peer else "(l.entry_seq = :s OR l.peer_seq = :s)"
    row = conn.execute(text(f"{ACTIVE} AND {where}"), {"s": entry_seq}).first()
    return row is not None


@dataclass(frozen=True)
class Move:
    seq: int
    on: str
    role: str  # trade | income | fee | in | out | stake (relié à une mise ou un claim)
    amount: int  # centimes de la devise de base, signé
    symbol: str
    quantity: Decimal  # parts signées
    internal: bool  # relié : entre mes comptes, ou staking
    account_id: str
    entry_id: str  # identifiant stable de l'écriture (le même après une reconstruction)

    @property
    def leg(self) -> Leg:
        return (
            self.on,
            self.role,
            self.amount,
            self.symbol,
            self.quantity,
            self.internal,
            self.account_id,
        )


Leg = tuple[
    str, str, int, str, Decimal, bool, str
]  # jour, rôle, montant, actif, parts, interne, compte


def moves(conn: Connection, on_date: str, *, account_id: str | None = None) -> list[Move]:
    """Les mouvements crypto jusqu'à `on_date`, dans l'ordre ; une monnaie (francs en attente chez
    la plateforme) n'en est pas un."""
    rows = conn.execute(
        text(
            "SELECT m.entry_seq, e.booking_date, m.role, e.amount_minor, m.asset, m.quantity, "
            "e.account_id, e.id, (SELECT group_concat(l.kind) FROM crypto_links l "
            "LEFT JOIN crypto_link_withdrawals w ON w.link_id = l.id WHERE w.link_id IS NULL "
            "AND (l.entry_seq = m.entry_seq OR l.peer_seq = m.entry_seq)) "
            "FROM crypto_moves m JOIN entries e ON e.seq = m.entry_seq "
            "JOIN accounts a ON a.id = e.account_id "
            "WHERE a.kind = 'crypto' AND e.booking_date <= :d "
            "AND (:a IS NULL OR e.account_id = :a) ORDER BY e.booking_date, e.seq"
        ),
        {"d": on_date, "a": account_id},
    ).fetchall()
    out = []
    for seq, on, found, amount, symbol, qty, account, entry_id, kinds in rows:
        if instruments.known_currency(str(symbol)):
            continue
        try:
            q = Decimal(str(qty))
        except ArithmeticError:
            continue
        if not q:
            continue
        linked_kinds = set(str(kinds).split(",")) if kinds else set()
        kind = str(found)
        if "stake" in linked_kinds and kind in ("in", "out"):
            kind = "stake"
        out.append(
            Move(
                int(seq),
                str(on),
                kind,
                int(amount),
                str(symbol).upper(),
                q,
                bool(linked_kinds),
                str(account),
                str(entry_id),
            )
        )
    return out


def legs(conn: Connection, on_date: str) -> list[Leg]:
    return [m.leg for m in moves(conn, on_date)]


def brief(conn: Connection, entry_id: str) -> dict[str, Any]:
    """Un mouvement pour une carte : jour, compte, rôle, actif, parts, montant (des agrégats
    d'une opération, jamais son libellé). `entry_id` est l'identifiant stable de l'écriture."""
    row = conn.execute(
        text(
            "SELECT e.booking_date, coalesce(nullif(a.name, ''), a.institution, a.id), m.role, "
            "m.asset, m.quantity, e.amount_minor, e.currency, e.seq "
            "FROM crypto_moves m JOIN entries e ON e.seq = m.entry_seq "
            "JOIN accounts a ON a.id = e.account_id WHERE e.id = :i"
        ),
        {"i": entry_id},
    ).first()
    if row is None:
        raise Problem("not_found", "mouvement crypto inconnu")
    return {
        "entry_id": entry_id,
        "entry_seq": int(row[7]),
        "on_date": row[0],
        "account": row[1],
        "role": row[2],
        "asset": row[3],
        "quantity": row[4],
        "amount": {"minor": int(row[5]), "currency": row[6]},
    }


def active_link(conn: Connection, entry_seq: int, kind: str, peer_seq: int | None) -> str | None:
    """L'identifiant du lien actif entre ces deux mouvements, s'il existe."""
    row = conn.execute(
        text(
            f"{ACTIVE} AND l.kind = :k AND ((l.entry_seq = :e AND l.peer_seq IS :p) "
            "OR (l.entry_seq = :p AND l.peer_seq = :e))"
        ),
        {"k": kind, "e": entry_seq, "p": peer_seq},
    ).first()
    return None if row is None else str(row[0])


def carry_over(src: Connection, dst: Connection) -> int:
    """Reconstruction : les liens que ni une source ni une proposition ne rejouent (ceux de la
    migration 0022) passent dans la base rebâtie, par l'identifiant stable des écritures ; leurs
    lignes de retrait suivent. Renvoie le nombre de liens recopiés."""
    seqs = {
        str(r[0]): int(r[1])
        for r in dst.execute(
            text("SELECT id, seq FROM entries WHERE seq IN (SELECT entry_seq FROM crypto_moves)")
        )
    }
    rows = src.execute(
        text(
            "SELECT l.id, e.id, l.kind, p.id, l.method, l.created_at, l.actor, "
            "w.created_at, w.actor, w.proposal_id FROM crypto_links l "
            "JOIN entries e ON e.seq = l.entry_seq LEFT JOIN entries p ON p.seq = l.peer_seq "
            "LEFT JOIN crypto_link_withdrawals w ON w.link_id = l.id "
            "WHERE l.actor NOT IN ('import', 'proposal') ORDER BY l.rowid"
        )
    ).fetchall()
    n = 0
    for link_id, entry_id, kind, peer_id, method, at, actor, w_at, w_actor, w_pid in rows:
        entry_seq = seqs.get(str(entry_id))
        peer_seq = seqs.get(str(peer_id)) if peer_id is not None else None
        if entry_seq is None or (peer_id is not None and peer_seq is None):
            continue  # une écriture que le rejeu n'a pas reproduite : rien à relier
        dst.execute(
            text(
                "INSERT INTO crypto_links (id, entry_seq, kind, peer_seq, method, proposal_id, "
                "created_at, actor) VALUES (:id, :e, :k, :p, :m, NULL, :at, :actor)"
            ),
            {
                "id": link_id,
                "e": entry_seq,
                "k": kind,
                "p": peer_seq,
                "m": method,
                "at": at,
                "actor": actor,
            },
        )
        if w_at is not None:
            dst.execute(
                text(
                    "INSERT INTO crypto_link_withdrawals (link_id, proposal_id, created_at, actor) "
                    "VALUES (:id, :p, :at, :actor)"
                ),
                {"id": link_id, "p": w_pid, "at": w_at, "actor": w_actor},
            )
        n += 1
    return n
