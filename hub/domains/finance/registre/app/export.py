"""Export CSV du journal (ticket L2-02) : chaque écriture telle qu'elle est au registre, avec sa
catégorie ; une cellule qui commencerait une formule est neutralisée."""

from __future__ import annotations

import csv
import io
from collections.abc import Iterator
from typing import Any

from sqlalchemy import Connection, text

from hub.kernel.money import Money

EXPORT_COLUMNS = (
    "id",
    "booking_date",
    "value_date",
    "account",
    "account_iban",
    "kind",
    "amount",
    "currency",
    "counterparty",
    "counterparty_iban",
    "label",
    "remittance",
    "bank_ref",
    "bank_tx_code",
    "category",
    "category_source",
    "import_id",
)
_FORMULA = ("=", "+", "-", "@", "\t", "\r")


def _cell(value: object) -> str:
    """Texte libre : neutralise ce qu'un tableur prendrait pour une formule."""
    s = "" if value is None else str(value)
    return "'" + s if s.startswith(_FORMULA) else s


def row(r: tuple[Any, ...]) -> list[str]:
    """Une ligne du CSV : toute colonne de texte passe par `_cell`, la référence bancaire et les
    IBAN compris (audit m15), les montants et les dates sont rendus par le hub."""
    out = [str(r[0]), str(r[1])]
    for i in range(2, 17):
        out.append(Money(int(r[6]), r[7]).display() if i == 6 else _cell(r[i]))
    return out


def export_csv(conn: Connection, date_from: str | None, date_to: str | None) -> Iterator[str]:
    """Journal complet, une ligne par écriture, par paquets de 500 lignes."""
    rows = conn.execute(
        text(
            "SELECT e.id, e.booking_date, e.value_date, a.name, a.iban, e.kind, e.amount_minor, "
            "e.currency, e.counterparty, e.counterparty_iban, e.label, e.remittance, e.bank_ref, "
            "e.bank_tx_code, vc.category_id, vc.source, e.import_id FROM entries e "
            "JOIN accounts a ON a.id = e.account_id "
            "LEFT JOIN v_entry_category vc ON vc.entry_seq = e.seq "
            "WHERE (:f IS NULL OR e.booking_date >= :f) AND (:t IS NULL OR e.booking_date <= :t) "
            "ORDER BY e.booking_date, e.seq"
        ),
        {"f": date_from, "t": date_to},
    )
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\r\n")
    writer.writerow(EXPORT_COLUMNS)
    for i, r in enumerate(rows, 1):
        writer.writerow(row(tuple(r)))
        if i % 500 == 0:
            yield buf.getvalue()
            buf.seek(0)
            buf.truncate()
    yield buf.getvalue()
