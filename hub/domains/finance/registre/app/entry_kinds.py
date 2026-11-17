"""Propositions du registre (ticket L3-02) : une note sur une écriture, une catégorie nouvelle."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Annotated, Any, Literal

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


Mode = Literal["target", "tracked", "off_budget"]
# une icône de l'app et sa teinte (« cart:3 ») ; None : celle du pack
Icon = Annotated[str, Field(pattern=r"^[a-z0-9-]{1,30}:[0-9]{1,2}$")]


class CreateCategory(Params):
    # sans identifiant, le hub le tire du nom (le front n'en invente pas)
    id: Slug | None = None
    name: str = Field(min_length=1, max_length=60)
    grp: Literal["fixed", "variable", "savings", "income", "transfer"]
    mode: Mode | None = None  # None : le mode par défaut du pack
    icon: Icon | None = None


def slug_for(conn: Connection, name: str) -> str:
    """Un identifiant libre tiré du nom : « Cours de piano » → « cours-de-piano », puis
    « cours-de-piano-2 » s'il est pris."""
    base = re.sub(r"[^a-z0-9]+", "-", normalize(name)).strip("-")[:36].strip("-") or "categorie"
    if len(base) < 2:
        base = f"categorie-{base}"
    taken = {str(r[0]) for r in conn.execute(text("SELECT id FROM categories"))}
    found, n = base, 2
    while found in taken:
        found, n = f"{base}-{n}", n + 1
    return found


class CreateCategoryHandler:
    def _id(self, conn: Connection, params: CreateCategory) -> str:
        return params.id or slug_for(conn, params.name)

    def preview(self, conn: Connection, params: BaseModel) -> Preview:
        assert isinstance(params, CreateCategory)  # noqa: S101
        new = self._id(conn, params)
        if conn.execute(text("SELECT 1 FROM categories WHERE id = :i"), {"i": new}).first():
            raise bad(f"catégorie déjà connue : {new}")
        named = conn.execute(
            text("SELECT 1 FROM categories WHERE lower(name) = lower(:n) AND active = 1"),
            {"n": params.name},
        ).first()
        if named:
            raise bad(f"une catégorie s'appelle déjà « {params.name} »")
        return Preview(
            summary=f"Nouvelle catégorie « {params.name} » ({params.grp})",
            details={**params.model_dump(), "id": new},
            fingerprint=fp("create_category", "absent", new),
        )

    def apply(self, conn: Connection, params: BaseModel, proposal_id: str) -> dict[str, Any]:
        assert isinstance(params, CreateCategory)  # noqa: S101
        new = self._id(conn, params)
        try:
            catalog.add_category(conn, id=new, name=params.name, grp=params.grp)
        except catalog.CatalogError as exc:
            raise bad(str(exc)) from None
        if params.mode is not None or params.icon is not None:
            conn.execute(
                text("UPDATE categories SET mode = :m, icon = :i WHERE id = :c"),
                {"m": params.mode, "i": params.icon, "c": new},
            )
        return {"category_id": new}
