"""Mouvements crypto entre mes comptes : l'autre côté d'un envoi ou d'une arrivée.

Un retrait d'une plateforme (Binance, SwissBorg) arrive sur un portefeuille (Ledger) ou sur une
autre plateforme ; un envoi depuis un portefeuille arrive sur une plateforme. L'autre côté est
une écriture d'un autre compte, de sens opposé, de la même crypto, à quelques jours près, pas
encore appariée, et :

1. du même txId sur la chaîne, quand les deux côtés le connaissent ;
2. sinon de la même quantité (la quantité nette de frais : ce qui arrive).

Le côté enregistré en second prend la valeur du premier et le lien s'écrit (`crypto_links`,
crypto_moves.py) : les deux écritures ont le même montant et deviennent un virement entre mes
comptes (`transfers`).
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import Connection, text

WINDOW_DAYS = 5  # un retrait arrive sur l'autre compte dans ce délai
SLACK_DAYS = 1  # dates UTC d'un côté, locales de l'autre


def normalize_txid(value: str | None) -> str:
    out = (value or "").strip().lower()
    return out[2:] if out.startswith("0x") else out


def counterpart(
    conn: Connection,
    account_ref: str,
    symbol: str,
    on: str,
    quantity: Decimal,
    txid: str | None = None,
) -> tuple[int, int, str] | None:
    """L'autre côté d'un mouvement de `quantity` (positif : arrivée) : (seq, montant, méthode
    `txid` ou `quantity`), parmi les mouvements crypto pas encore reliés."""
    day = date.fromisoformat(on)
    if quantity > 0:
        start, end, sign = day - timedelta(days=WINDOW_DAYS), day + timedelta(days=SLACK_DAYS), "<"
    else:
        start, end, sign = day - timedelta(days=SLACK_DAYS), day + timedelta(days=WINDOW_DAYS), ">"
    rows = conn.execute(
        text(
            "SELECT e.seq, e.amount_minor, m.quantity, m.txid, e.booking_date "  # noqa: S608
            "FROM crypto_moves m JOIN entries e ON e.seq = m.entry_seq "
            "JOIN accounts a ON a.id = e.account_id "
            f"WHERE m.role IN ('in', 'out') AND e.amount_minor {sign} 0 AND a.external_ref != :acc "
            "AND e.booking_date BETWEEN :s AND :d AND m.asset = :c "
            "AND NOT EXISTS (SELECT 1 FROM crypto_links l "
            "  LEFT JOIN crypto_link_withdrawals w ON w.link_id = l.id "
            "  WHERE w.link_id IS NULL AND (l.entry_seq = e.seq OR l.peer_seq = e.seq)) "
            "ORDER BY abs(julianday(e.booking_date) - julianday(:on)), e.seq"
        ),
        {"acc": account_ref, "s": start.isoformat(), "d": end.isoformat(), "c": symbol, "on": on},
    ).fetchall()
    mine = normalize_txid(txid)
    by_quantity = None
    for seq, amount, qty, their_txid, _on in rows:
        theirs = normalize_txid(their_txid)
        if mine and theirs:
            if mine == theirs:
                return int(seq), int(amount), "txid"
            continue  # deux transactions différentes sur la chaîne
        try:
            same = qty is not None and -Decimal(str(qty)) == quantity
        except ArithmeticError:
            same = False
        if same and by_quantity is None:
            by_quantity = int(seq), int(amount), "quantity"
    return by_quantity
