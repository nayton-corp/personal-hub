"""Mouvements crypto entre mes comptes : l'autre côté d'un envoi ou d'une arrivée.

Un retrait d'une plateforme (Binance, SwissBorg) arrive sur un portefeuille (Ledger) ou sur une
autre plateforme ; un envoi depuis un portefeuille arrive sur une plateforme. L'autre côté est
une écriture d'un autre compte, de sens opposé, de la même crypto, à quelques jours près, pas
encore appariée, et :

1. du même txId sur la chaîne, quand les deux côtés le connaissent ;
2. sinon de la même quantité (la quantité nette de frais : ce qui arrive).

Le côté enregistré en second prend la valeur du premier (`peer` dans son détail) : les deux
écritures ont le même montant et deviennent un virement entre mes comptes (`transfers`).
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import Connection, text

from hub.domains.finance import institutions

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
) -> tuple[int, int] | None:
    """L'autre côté d'un mouvement de `quantity` (positif : arrivée) : (seq, montant)."""
    day = date.fromisoformat(on)
    if quantity > 0:
        start, end, sign = day - timedelta(days=WINDOW_DAYS), day + timedelta(days=SLACK_DAYS), "<"
    else:
        start, end, sign = day - timedelta(days=SLACK_DAYS), day + timedelta(days=WINDOW_DAYS), ">"
    codes = institutions.like_any("e.bank_tx_code", institutions.prefixes(transfer=True))
    taken = institutions.like_any("x.bank_tx_code", institutions.prefixes(transfer=True))
    rows = conn.execute(
        text(
            "SELECT e.seq, e.amount_minor, json_extract(e.fx_json, '$.quantity'), "  # noqa: S608 - codes déclarés
            "json_extract(e.fx_json, '$.txid'), e.booking_date "
            "FROM entries e JOIN accounts a ON a.id = e.account_id "
            f"WHERE ({codes}) AND e.amount_minor {sign} 0 AND a.external_ref != :acc "
            "AND e.booking_date BETWEEN :s AND :d "
            "AND json_extract(e.fx_json, '$.currency') = :c "
            "AND json_extract(e.fx_json, '$.peer') IS NULL "
            f"AND NOT EXISTS (SELECT 1 FROM entries x WHERE ({taken}) "
            "  AND CAST(json_extract(x.fx_json, '$.peer') AS INTEGER) = e.seq) "
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
                return int(seq), int(amount)
            continue  # deux transactions différentes sur la chaîne
        try:
            same = qty is not None and -Decimal(str(qty)) == quantity
        except ArithmeticError:
            same = False
        if same and by_quantity is None:
            by_quantity = int(seq), int(amount)
    return by_quantity
