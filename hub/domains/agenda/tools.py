"""Outils de l'agenda pour l'assistant : lire (agenda:read), compter (agenda:aggregates),
proposer un ajout ou une case cochée (agenda:propose). Un outil qui écrit crée une proposition ;
la liste de courses passe au palier automatique."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from pydantic import BaseModel, ValidationError

from hub.core.domain import McpTool, ToolCaller
from hub.core.errors import Problem
from hub.domains.agenda.bridge import BridgeError
from hub.domains.agenda.kinds import AddEvent, AddReminder, AddShopping, CompleteReminder

READ, AGGREGATES, PROPOSE = "agenda:read", "agenda:aggregates", "agenda:propose"


class Host(Protocol):
    def upcoming(self, days: int = 7) -> dict[str, Any]: ...

    def counts(self) -> dict[str, Any]: ...


def _schema(model: type[BaseModel]) -> dict[str, Any]:
    schema = model.model_json_schema()
    return {
        "type": "object",
        "properties": schema.get("properties", {}),
        "required": schema.get("required", []),
        "additionalProperties": False,
    }


def _read(fn: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    try:
        return {"available": True, **fn()}
    except BridgeError as exc:
        return {"available": False, "reason": str(exc)}


def _propose(kind: str, model: type[BaseModel]) -> Callable[[dict[str, Any], ToolCaller], Any]:
    def call(args: dict[str, Any], caller: ToolCaller) -> Any:
        try:
            params = model.model_validate(args)
        except ValidationError as exc:
            errors = [{"loc": list(e["loc"]), "type": e["type"]} for e in exc.errors()]
            raise Problem("validation.params", errors=errors) from None
        return caller.propose(kind, params.model_dump(mode="json", exclude_none=True))

    return call


def build(host: Host) -> list[McpTool]:
    days = {
        "type": "object",
        "properties": {"days": {"type": "integer", "minimum": 1, "maximum": 31}},
        "additionalProperties": False,
    }
    return [
        McpTool(
            "agenda_upcoming",
            "Les événements des prochains jours (7 par défaut), les rappels ouverts et la liste "
            "de courses, avec leurs identifiants.",
            days,
            READ,
            lambda args, _c: _read(lambda: host.upcoming(int(args.get("days") or 7))),
        ),
        McpTool(
            "agenda_counts",
            "Combien d'événements cette semaine, de rappels ouverts ou en retard, d'articles à "
            "acheter (des nombres, jamais les titres).",
            {"type": "object", "properties": {}, "additionalProperties": False},
            AGGREGATES,
            lambda _args, _c: _read(host.counts),
        ),
        McpTool(
            "agenda_propose_reminder",
            "Propose un rappel (titre, liste, échéance) : une carte à valider dans l'app.",
            _schema(AddReminder),
            PROPOSE,
            _propose("add_reminder", AddReminder),
        ),
        McpTool(
            "agenda_propose_event",
            "Propose un événement du calendrier (titre, début, fin) : une carte à valider.",
            _schema(AddEvent),
            PROPOSE,
            _propose("add_event", AddEvent),
        ),
        McpTool(
            "agenda_propose_complete",
            "Propose de cocher un rappel (son identifiant, tel que rendu par agenda_upcoming).",
            _schema(CompleteReminder),
            PROPOSE,
            _propose("complete_reminder", CompleteReminder),
        ),
        McpTool(
            "agenda_add_shopping",
            "Ajoute un article à la liste de courses (palier automatique, sans carte).",
            _schema(AddShopping),
            PROPOSE,
            _propose("add_shopping", AddShopping),
        ),
    ]
