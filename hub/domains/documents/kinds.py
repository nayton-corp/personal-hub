"""Les types de proposition des documents : compléter une fiche d'objet (l'assistant peut le
proposer), marquer un document « foyer » ou le rendre privé (l'app seule, réversible)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import Connection

from hub.core.domain import Preview, ProposalKind
from hub.core.errors import Problem
from hub.domains.documents import store
from hub.domains.documents.model import CardError, check_card, merged, plain
from hub.domains.documents.service import Library
from hub.kernel import canonical


class SaveCard(BaseModel):
    model_config = ConfigDict(extra="forbid")
    card_id: str = Field(min_length=1, max_length=80)
    fields: dict[str, Any]

    @field_validator("fields")
    @classmethod
    def _known(cls, v: dict[str, Any], info: Any) -> dict[str, Any]:
        try:
            check_card(info.data.get("card_id") or "x", v)
        except CardError as exc:
            raise ValueError(str(exc)) from None
        return v


class MarkHousehold(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_id: str = Field(min_length=1, max_length=64)
    household: bool


class CardHandler:
    def __init__(self, library: Library) -> None:
        self._library = library

    def preview(self, conn: Connection, params: BaseModel) -> Preview:
        assert isinstance(params, SaveCard)  # noqa: S101
        current = store.card(conn, params.card_id)
        card = merged(current, plain(params.fields))
        changed = sorted(k for k in card if (current or {}).get(k) != card[k])
        name = card.get("name") or params.card_id
        verb = "Nouvelle fiche" if current is None else "Fiche"
        return Preview(
            f"{verb} « {name} » : {', '.join(changed) or 'rien ne change'}",
            {"card_id": params.card_id, "changed": changed},
            canonical.sha256_hex({"card": current}),
        )

    def apply(self, conn: Connection, params: BaseModel, proposal_id: str) -> dict[str, Any]:
        assert isinstance(params, SaveCard)  # noqa: S101
        changed = self._library.save_card(conn, params.card_id, params.fields)
        return {"card_id": params.card_id, "changed": changed}

    def after_commit(self, params: BaseModel, result: dict[str, Any]) -> None:
        self._library.export()


class MarkHandler:
    def __init__(self, library: Library) -> None:
        self._library = library

    def preview(self, conn: Connection, params: BaseModel) -> Preview:
        assert isinstance(params, MarkHousehold)  # noqa: S101
        doc = store.document(conn, params.document_id)
        if doc is None:
            raise Problem("not_found", "document inconnu")
        who = "lisible par tout le foyer" if params.household else "réservé aux propriétaires"
        return Preview(
            f"« {doc['title']} » {who}",
            {"document_id": doc["id"], "household": params.household},
            canonical.sha256_hex({"household": doc["household"]}),
        )

    def apply(self, conn: Connection, params: BaseModel, proposal_id: str) -> dict[str, Any]:
        assert isinstance(params, MarkHousehold)  # noqa: S101
        if store.document(conn, params.document_id) is None:
            raise Problem("not_found", "document inconnu")
        store.add_mark(conn, params.document_id, params.household)
        return {"document_id": params.document_id, "household": params.household}

    def after_commit(self, params: BaseModel, result: dict[str, Any]) -> None:
        self._library.export()


def _unmark(params: dict[str, Any], _result: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    return "mark_household", {**params, "household": not params["household"]}


def kinds(lib: Library) -> Mapping[str, ProposalKind]:
    return {
        "save_card": ProposalKind(SaveCard, CardHandler(lib), ai_allowed=True),
        "mark_household": ProposalKind(
            MarkHousehold, MarkHandler(lib), reversible=True, inverse=_unmark
        ),
    }
