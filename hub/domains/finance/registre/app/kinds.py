"""Briques des types de proposition (ticket L3-02) : paramètres figés, empreinte, refus, et la
forme d'une écriture ou d'un total dans un aperçu."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection, text

from hub.core.errors import Problem
from hub.domains.finance.registre.app import ledger
from hub.kernel import canonical
from hub.kernel.money import Money

if TYPE_CHECKING:
    pass


SAMPLE = 10  # écritures montrées dans un aperçu ; les totaux portent sur toutes
Slug = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9-]{1,40}$")]
EntryId = Annotated[str, Field(min_length=2, max_length=40, pattern=r"^e[0-9a-f]+$")]


class Params(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def fp(*parts: object) -> str:
    return canonical.sha256_hex(list(parts))


def bad(detail: str) -> Problem:
    return Problem("validation.params", detail)


def shown_amount(minor: int, currency: str) -> str:
    return f"{Money(minor, currency).display()} {currency}"


def category_row(conn: Connection, category_id: str) -> tuple[str, str]:
    row = conn.execute(
        text("SELECT name, grp, active FROM categories WHERE id = :c"), {"c": category_id}
    ).first()
    if row is None or not row[2]:
        raise bad(f"catégorie inconnue ou inactive : {category_id}")
    return str(row[0]), str(row[1])


def entry_brief(r: Any) -> dict[str, Any]:
    return {
        "id": r.id,
        "booking_date": r.booking_date,
        "amount": Money(int(r.amount_minor), r.currency).to_api(),
        "counterparty": ledger.party(r.counterparty) or r.label or None,
    }


def entry_row(conn: Connection, entry_id: str) -> Any:
    row = conn.execute(
        text(
            "SELECT e.seq, e.id, e.kind, e.booking_date, e.amount_minor, e.currency, "
            "e.counterparty, e.label, vc.category_id, vc.categorization_seq "
            "FROM entries e LEFT JOIN v_entry_category vc ON vc.entry_seq = e.seq "
            "WHERE e.id = :i"
        ),
        {"i": entry_id},
    ).first()
    if row is None:
        raise bad("écriture inconnue")
    return row


def totals_by_currency(items: list[tuple[int, str]]) -> list[dict[str, Any]]:
    sums: dict[str, int] = {}
    for minor, ccy in items:
        sums[ccy] = sums.get(ccy, 0) + minor
    return [Money(v, k).to_api() for k, v in sorted(sums.items())]
