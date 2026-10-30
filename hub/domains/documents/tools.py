"""Outils des documents pour l'assistant. `documents:household` ouvre les fiches d'objets et les
documents marqués « foyer » (ce que tout le foyer peut lire) ; `documents:read` ouvre aussi les
documents privés ; `documents:aggregates` ne voit que des nombres ; `documents:propose`
propose de compléter une fiche (une carte dans l'app)."""

from __future__ import annotations

from typing import Any, Protocol

from pydantic import ValidationError

from hub.core.domain import McpTool, ToolCaller
from hub.core.errors import Problem
from hub.domains.documents.kinds import SaveCard

READ, HOUSEHOLD = "documents:read", "documents:household"
AGGREGATES, PROPOSE = "documents:aggregates", "documents:propose"


class Host(Protocol):
    def find(self, q: str, limit: int, household_only: bool) -> dict[str, Any]: ...

    def card_list(self) -> list[dict[str, Any]]: ...

    def card_view(self, card_id: str, household_only: bool) -> dict[str, Any] | None: ...

    def due(self) -> list[dict[str, Any]]: ...

    def counts(self) -> dict[str, int]: ...


def _private(caller: ToolCaller) -> bool:
    """Vrai si l'appelant ne lit que la part du foyer."""
    return not caller.allows(READ)


def _save(args: dict[str, Any], caller: ToolCaller) -> Any:
    try:
        params = SaveCard.model_validate(args)
    except ValidationError as exc:
        errors = [{"loc": list(e["loc"]), "type": e["type"]} for e in exc.errors()]
        raise Problem("validation.params", errors=errors) from None
    return caller.propose("save_card", params.model_dump(mode="json"))


def _card(host: Host, args: dict[str, Any], caller: ToolCaller) -> Any:
    found = host.card_view(str(args.get("card_id") or ""), _private(caller))
    if found is None:
        raise Problem("not_found", "fiche inconnue")
    return found


def build(host: Host) -> list[McpTool]:
    empty = {"type": "object", "properties": {}, "additionalProperties": False}
    search = {
        "type": "object",
        "properties": {
            "q": {"type": "string", "minLength": 3, "maxLength": 200},
            "limit": {"type": "integer", "minimum": 1, "maximum": 20},
        },
        "required": ["q"],
        "additionalProperties": False,
    }
    card = {
        "type": "object",
        "properties": {"card_id": {"type": "string", "minLength": 1, "maxLength": 80}},
        "required": ["card_id"],
        "additionalProperties": False,
    }
    save = {
        "type": "object",
        "properties": {
            "card_id": card["properties"]["card_id"],  # type: ignore[index]
            "fields": {"type": "object"},
        },
        "required": ["card_id", "fields"],
        "additionalProperties": False,
    }
    return [
        McpTool(
            "documents_search",
            "Cherche dans les documents (notices, contrats, garanties, factures) et les fiches "
            "d'objets : les passages trouvés, avec leur source et leur page à citer.",
            search,
            HOUSEHOLD,
            lambda a, c: host.find(str(a["q"]), int(a.get("limit") or 5), _private(c)),
        ),
        McpTool(
            "documents_cards",
            "Les fiches d'objets de la maison (identifiant, nom, pièce).",
            empty,
            HOUSEHOLD,
            lambda _a, _c: host.card_list(),
        ),
        McpTool(
            "documents_card",
            "Une fiche d'objet entière (marque, modèle, numéro de série, garantie, entretien, "
            "pièces) et ses documents.",
            card,
            HOUSEHOLD,
            lambda a, c: _card(host, a, c),
        ),
        McpTool(
            "documents_maintenance_due",
            "Les entretiens dont l'échéance est passée, d'après les fiches d'objets.",
            empty,
            HOUSEHOLD,
            lambda _a, _c: host.due(),
        ),
        McpTool(
            "documents_counts",
            "Combien de fiches, de documents, de documents du foyer et d'entretiens dus.",
            empty,
            AGGREGATES,
            lambda _a, _c: host.counts(),
        ),
        McpTool(
            "documents_propose_card",
            "Propose de créer ou de compléter une fiche d'objet (champs : name, room, brand, "
            "model, serial, bought_at, shop, price_chf, warranty_until, maintenance, parts, "
            "notes) : une carte à valider dans l'app.",
            save,
            PROPOSE,
            _save,
        ),
    ]
