"""Écriture d'ouverture d'un compte : une seule, avant toute autre, sa clé tirée de l'IBAN."""

from __future__ import annotations

from sqlalchemy import Connection, text

from hub.domains.finance.registre.app import catalog, ledger
from hub.domains.finance.registre.model import dedup
from hub.domains.finance.registre.model.errors import ImportRefused


def open_account(
    conn: Connection, account_id: str, booking_date: str, amount_minor: int, currency: str
) -> int:
    """Écriture d'ouverture, une seule par compte. Sa clé vient de l'IBAN (ou de la référence
    externe), pas du ULID du compte : une reconstruction redonne le même identifiant."""
    account = catalog.get_account(conn, account_id)
    if conn.execute(
        text("SELECT 1 FROM entries WHERE account_id = :a LIMIT 1"), {"a": account_id}
    ).first():
        raise ImportRefused("import.before_opening", "le registre de ce compte est déjà ouvert")
    seq, _ = ledger.append_entry(
        conn,
        ledger.NewEntry(
            account_id=account_id,
            kind="opening",
            booking_date=booking_date,
            amount_minor=amount_minor,
            currency=currency,
            dedup_key=dedup.opening_key(account.iban or account.external_ref or account.id),
            label="Solde d'ouverture",
        ),
    )
    return seq
