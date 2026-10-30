"""Propositions du registre (ticket L3-02) : une note sur une écriture, une catégorie nouvelle."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import Connection, text

from hub.core.domain import Preview
from hub.domains.finance.registre.app import catalog, ledger
from hub.domains.finance.registre.app.kinds import (
    EntryId,
    Params,
    Slug,
    bad,
    entry_brief,
    entry_row,
    fp,
    shown_amount,
)
from hub.kernel.clock import now_iso
from hub.kernel.text import normalize

if TYPE_CHECKING:
    pass


class AddNote(Params):
    entry_id: EntryId
    text: str = Field(min_length=1, max_length=1000)


class AddNoteHandler:
    def _last(self, conn: Connection, entry_seq: int) -> int:
        return int(
            conn.execute(
                text("SELECT coalesce(max(seq), 0) FROM notes WHERE entry_seq = :e"),
                {"e": entry_seq},
            ).scalar_one()
        )

    def preview(self, conn: Connection, params: BaseModel) -> Preview:
        assert isinstance(params, AddNote)  # noqa: S101
        e = entry_row(conn, params.entry_id)
        return Preview(
            summary=f"Note sur 1 écriture ({shown_amount(e.amount_minor, e.currency)})",
            details={"entries": [entry_brief(e)], "text": params.text},
            fingerprint=fp("add_note", e.id, self._last(conn, e.seq)),
        )

    def apply(self, conn: Connection, params: BaseModel, proposal_id: str) -> dict[str, Any]:
        assert isinstance(params, AddNote)  # noqa: S101
        e = entry_row(conn, params.entry_id)
        seq = ledger.append(
            conn,
            "notes",
            {
                "entry_seq": e.seq,
                "text": params.text,
                "search_text": normalize(params.text),
                "proposal_id": proposal_id,
                "created_at": now_iso(),
            },
        )
        return {"entry_id": e.id, "note_seq": seq}


class CreateCategory(Params):
    id: Slug
    name: str = Field(min_length=1, max_length=60)
    grp: Literal["fixed", "variable", "savings", "income", "transfer"]


class CreateCategoryHandler:
    def preview(self, conn: Connection, params: BaseModel) -> Preview:
        assert isinstance(params, CreateCategory)  # noqa: S101
        if conn.execute(text("SELECT 1 FROM categories WHERE id = :i"), {"i": params.id}).first():
            raise bad(f"catégorie déjà connue : {params.id}")
        return Preview(
            summary=f"Nouvelle catégorie « {params.name} » ({params.grp})",
            details=params.model_dump(),
            fingerprint=fp("create_category", "absent", params.id),
        )

    def apply(self, conn: Connection, params: BaseModel, proposal_id: str) -> dict[str, Any]:
        assert isinstance(params, CreateCategory)  # noqa: S101
        try:
            catalog.add_category(conn, id=params.id, name=params.name, grp=params.grp)
        except catalog.CatalogError as exc:
            raise bad(str(exc)) from None
        return {"category_id": params.id}
