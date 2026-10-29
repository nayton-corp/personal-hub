"""Export CSV du journal (ticket L2-02) : chaque écriture telle qu'elle est au registre, avec sa
catégorie ; une cellule qui commencerait une formule est neutralisée."""

from __future__ import annotations

import csv
import io
from collections.abc import Iterator

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
        writer.writerow(
            [
                r[0],
                r[1],
                r[2] or "",
                _cell(r[3]),
                r[4] or "",
                r[5],
                Money(int(r[6]), r[7]).display(),
                r[7],
                _cell(r[8]),
                r[9] or "",
                _cell(r[10]),
                _cell(r[11]),
                r[12] or "",
                r[13] or "",
                r[14] or "",
                r[15] or "",
                r[16] or "",
            ]
        )
        if i % 500 == 0:
            yield buf.getvalue()
            buf.seek(0)
            buf.truncate()
    yield buf.getvalue()
