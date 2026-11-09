"""Échange de fonds VIAC (« Transaction de fonds ») : VIAC fusionne un fonds dans un autre à
valeur égale (fin octobre 2026 : fonds CS repris par UBS). Les parts de l'ancien ISIN sortent
et celles du nouveau entrent, sans écriture de liquidités ni de titres : la valeur du compte ne
bouge pas, seule sa composition change.

Deux lignes de `trades` sur le compte titres : la sortie au coût moyen de l'ancien fonds (ce
que les avis ont payé, au prorata des parts sorties) et l'entrée au même coût, que la
performance « depuis l'achat » garde ainsi d'un fonds à l'autre.
"""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal, localcontext

from sqlalchemy import Connection, text

from hub.domains.finance.registre.app import ledger
from hub.domains.finance.sources.model.viac import Notice
from hub.kernel.clock import now_iso
from hub.kernel.money import DECIMAL_CONTEXT


def cost_of(conn: Connection, account_id: str, isin: str, on: str, quantity: Decimal) -> int:
    """Coût (centimes) de `quantity` parts de `isin`, au coût moyen des opérations connues."""
    rows = conn.execute(
        text(
            "SELECT quantity, amount_minor FROM trades WHERE account_id = :a AND isin = :i "
            "AND trade_date <= :d"
        ),
        {"a": account_id, "i": isin, "d": on},
    ).all()
    with localcontext(DECIMAL_CONTEXT):
        held = sum((Decimal(q) for q, _ in rows), Decimal(0))
        paid = sum((int(a) for _, a in rows), 0)
        if held <= 0 or paid <= 0:
            return 0
        share = Decimal(paid) * min(quantity, held) / held
        return int(share.quantize(Decimal(1), rounding=ROUND_HALF_EVEN))


def apply(conn: Connection, import_id: str, n: Notice, titles_id: str) -> tuple[int, int]:
    """(nouvelles lignes, doublons) de `trades` pour un échange de fonds."""
    from hub.domains.finance.sources.app.viac import qty_text, upsert_instrument

    if not (n.isin and n.new_isin and n.quantity and n.new_quantity):
        raise ValueError("échange de fonds incomplet")  # le parseur l'a déjà refusé
    cost = cost_of(conn, titles_id, n.isin, n.value_date, n.quantity)
    created = now_iso()
    new = duplicates = 0
    for isin, quantity, amount in (
        (n.isin, -n.quantity, -cost),
        (n.new_isin, n.new_quantity, cost),
    ):
        key = ledger.dedup_hash(
            f"viac|{n.portfolio}|switch|{n.value_date}|{n.isin}|{n.new_isin}|{isin}|"
            f"{qty_text(quantity)}"
        )
        if conn.execute(text("SELECT 1 FROM trades WHERE dedup_key = :k"), {"k": key}).first():
            duplicates += 1
            continue
        ledger.append(
            conn,
            "trades",
            {
                "account_id": titles_id,
                "trade_date": n.value_date,
                "isin": isin,
                "quantity": qty_text(quantity),
                "amount_minor": amount,
                "currency": "CHF",
                "dedup_key": key,
                "import_id": import_id,
                "created_at": created,
            },
        )
        new += 1
    upsert_instrument(conn, n.new_isin, n.new_fund or n.new_isin)
    return new, duplicates
