"""Les outils de l'assistant (spec §7) : un catalogue fermé, le même pour la boucle du modèle et le serveur MCP. Les
gestes sont générés depuis `GET /api/commands/catalog` (§7.2) : un geste ajouté à Domia arrive ici sans toucher
l'assistant ; jamais de `Toggle`. Chaque geste part au nom de la personne qui parle ; ceux qui touchent toute la maison
attendent un « oui » (§5.1)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from . import reading
from .agenda import Agenda
from .domia import Domia, DomiaError
from .library import Library
from .memory import Memory
from .tools_agenda import agenda_tools, planning_tools, web_tools
from .tools_base import (
    FAMILIES,
    FAMILY_OF,
    GLOSS,
    HOUSE_WIDE_SITUATIONS,
    KIND_PARAM,
    Speaker,
    Tool,
    compact_house,
    field_schema,
    obj,
)
from .tools_house import gesture_tools, read_tools
from .tools_knowledge import MIME, NAMEPLATE, library_tools, memory_tools, settings_tools

__all__ = [
    "FAMILIES",
    "FAMILY_OF",
    "GLOSS",
    "HOUSE_WIDE_SITUATIONS",
    "KIND_PARAM",
    "MIME",
    "NAMEPLATE",
    "Speaker",
    "Tool",
    "Toolbox",
    "agenda_tools",
    "build",
    "compact_house",
    "field_schema",
    "gesture_tools",
    "library_tools",
    "memory_tools",
    "obj",
    "planning_tools",
    "read_tools",
    "settings_tools",
    "web_tools",
]


class Toolbox:
    def __init__(
        self,
        tools: list[Tool],
        families: dict[str, str] | None = None,
        notes: str = "",
        owner: Speaker | None = None,
    ):
        self.tools = {t.name: t for t in tools}
        self.extra = families or {}  # les domaines du hub, en plus des types de la maison
        self.notes = notes  # leurs consignes, pour qui atteint leurs outils
        self.owner = owner  # une personne qui les atteint (le préchauffage de son préfixe)

    def families(self, who: Speaker | None = None) -> dict[str, str]:
        """Les types de demande que le routeur peut nommer pour cette personne."""
        seen = {f for t in self.tools.values() if t.family and t.allowed(who) for f in t.families}
        return {**FAMILIES, **{name: what for name, what in self.extra.items() if name in seen}}

    def schemas(self, families: frozenset[str] | None = None, who: Speaker | None = None) -> list[dict[str, Any]]:
        """Les outils montrés au modèle : tous, ou ceux de ces types de demande ; jamais un outil que la personne
        n'atteint pas (les outils du hub, pour Kim)."""
        return [
            t.schema() for t in self.tools.values() if t.allowed(who) and (families is None or t.families & families)
        ]

    def system_notes(self, who: Speaker | None) -> str:
        return self.notes if any(t.family and t.allowed(who) for t in self.tools.values()) else ""

    def get(self, name: str) -> Tool | None:
        return self.tools.get(name)

    def run(self, name: str, args: dict[str, Any], who: Speaker) -> Any:
        tool = self.tools.get(name)
        if tool is None or not tool.allowed(who):
            return {"error": f"outil inconnu : {name}"}
        try:
            result = tool.run(args, who)
            return result if tool.gesture else reading.fit(result)
        except DomiaError as e:
            return {"error": str(e)}
        except (KeyError, ValueError, TypeError, AttributeError) as e:  # au banc : une pièce donnée en objet
            return {"error": f"arguments invalides : {e}"}


def build(
    domia: Domia,
    library: Library | None,
    memory: Memory | None,
    agenda: Agenda | None,
    searx_url: str | None = None,
    look: Callable[[bytes, str, str], str] | None = None,
    zone: str = "Europe/Zurich",
    plan: Callable[[datetime, Any], Any] | None = None,
    engagements: Any | None = None,
    settings_write: bool = False,
    hub: Any | None = None,
) -> Toolbox:
    """Tous les outils, les gestes relus du catalogue et de la maison du moment."""
    house = domia.house()
    tools = (
        read_tools(domia, zone)
        + gesture_tools(domia.catalog(), house, domia)
        + planning_tools(domia, plan, engagements, zone)
    )
    if library:
        tools += library_tools(library, look)
    if memory:
        tools += memory_tools(memory) + (settings_tools(domia, memory) if settings_write else [])
    if agenda:
        tools += agenda_tools(agenda)
    tools += web_tools(searx_url)
    if hub is not None:  # domia_assistant.hub.HubModule
        return Toolbox(tools + hub.tools, hub.families, hub.notes, hub.owner)
    return Toolbox(tools)
