"""Routage des outils par domaine.

La passerelle n'expose pas tous les outils d'un coup : `hub_capabilities` décrit les domaines
ouverts au jeton, `hub_load_tools` charge ceux d'un domaine. Quand le jeton n'ouvre qu'un
domaine, ses outils sont chargés d'emblée (un aller-retour de moins pour un petit modèle).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from hub.brain.hubapi import HubApi, HubError

CAPABILITIES = "hub_capabilities"
LOAD = "hub_load_tools"


@dataclass(frozen=True)
class ToolResult:
    text: str  # JSON, tel que le modèle le lit
    is_error: bool = False
    tools_changed: bool = False
    data: Any = None


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


@dataclass
class Toolbox:
    api: HubApi
    autoload: bool = True
    domains: list[dict[str, Any]] = field(default_factory=list)
    loaded: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    owner: dict[str, str] = field(default_factory=dict)

    def start(self) -> None:
        self.domains = self.api.capabilities()
        if self.autoload and len(self.domains) == 1:
            self.load(self.domains[0]["domain"])

    def load(self, domain: str) -> list[str]:
        if domain not in self.loaded:
            items = self.api.tools(domain)
            self.loaded[domain] = items
            for t in items:
                self.owner[t["name"]] = domain
        return [t["name"] for t in self.loaded[domain]]

    def meta(self) -> list[dict[str, Any]]:
        names = [d["domain"] for d in self.domains]
        return [
            {
                "name": CAPABILITIES,
                "description": "Domaines du hub ouverts à ce jeton, avec leurs outils.",
                "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
            },
            {
                "name": LOAD,
                "description": "Charge les outils d'un domaine (voir hub_capabilities).",
                "input_schema": {
                    "type": "object",
                    "properties": {"domain": {"type": "string", "enum": names}},
                    "required": ["domain"],
                    "additionalProperties": False,
                },
            },
        ]

    def definitions(self) -> list[dict[str, Any]]:
        """Outils visibles maintenant : `name`, `description`, `input_schema`."""
        out = self.meta()
        for items in self.loaded.values():
            out.extend(items)
        return out

    def call(self, name: str, args: dict[str, Any] | None) -> ToolResult:
        args = args or {}
        if name == CAPABILITIES:
            caps = [{**d, "loaded": d["domain"] in self.loaded} for d in self.domains]
            return ToolResult(dumps({"domains": caps}), data=caps)
        if name == LOAD:
            domain = str(args.get("domain", ""))
            if domain not in {d["domain"] for d in self.domains}:
                return ToolResult(dumps({"error": f"domaine inconnu : {domain}"}), is_error=True)
            fresh = domain not in self.loaded
            try:
                names = self.load(domain)
            except HubError as exc:
                return self._error(exc)
            return ToolResult(dumps({"domain": domain, "tools": names}), tools_changed=fresh)
        owner = self.owner.get(name)
        if owner is None:
            return ToolResult(
                dumps({"error": f"outil non chargé : {name} ; appeler d'abord {LOAD}"}),
                is_error=True,
            )
        try:
            result = self.api.call(owner, name, args)
        except HubError as exc:
            return self._error(exc)
        return ToolResult(dumps(result), data=result)

    @staticmethod
    def _error(exc: HubError) -> ToolResult:
        body: dict[str, Any] = {"error": exc.type}
        if exc.detail:
            body["detail"] = exc.detail
        return ToolResult(dumps(body), is_error=True)
