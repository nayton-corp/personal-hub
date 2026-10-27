"""Outils de l'assistant (lot 7), côté cœur : qui voit quel outil, et ce qu'un outil peut faire.

La passerelle MCP du Mac ne connaît aucun domaine : elle demande au hub la liste des domaines
qu'ouvre son jeton (`hub_capabilities`), puis les outils d'un domaine à la demande. Les outils
s'exécutent ici, dans l'API, avec les portées du jeton appelant. Un modèle ne peut que lire et
créer des propositions ; rien ne s'applique sans une validation dans l'app.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from hub.core import collectors, proposals
from hub.core.auth import Principal
from hub.core.context import HubContext
from hub.core.domain import Domain, McpTool
from hub.core.errors import Problem


def tool_allowed(principal: Principal, tool: McpTool) -> bool:
    """La lecture complète d'un domaine ouvre aussi ses agrégats."""
    if principal.allows(tool.scope):
        return True
    domain, _, verb = tool.scope.partition(":")
    return verb == "aggregates" and principal.allows(f"{domain}:read")


def visible_tools(principal: Principal, domain: Domain) -> list[McpTool]:
    return [t for t in domain.mcp_tools() if tool_allowed(principal, t)]


def capabilities(hub: HubContext, principal: Principal) -> list[dict[str, Any]]:
    out = []
    for d in hub.registry:
        names = [t.name for t in visible_tools(principal, d)]
        if names:
            out.append(
                {
                    "domain": d.name,
                    "description": getattr(d, "description", d.name),
                    "tools": names,
                    "aggregates_only": not principal.allows_any(
                        f"{d.name}:read", f"{d.name}:propose"
                    ),
                }
            )
    return out


def find(principal: Principal, domain: Domain, name: str) -> McpTool:
    for t in domain.mcp_tools():
        if t.name == name:
            if not tool_allowed(principal, t):
                raise Problem("auth.scope")
            return t
    raise Problem("not_found", f"outil inconnu : {name}")


@dataclass
class Caller:
    """`ToolCaller` du contrat de domaine, lié à un jeton et à un domaine."""

    hub: HubContext
    principal: Principal
    domain: str

    @property
    def actor(self) -> str:
        return self.principal.actor

    def allows(self, scope: str) -> bool:
        return self.principal.allows(scope)

    def propose(
        self, kind: str, params: dict[str, Any], reason: str | None = None
    ) -> dict[str, Any]:
        p, created = proposals.create(
            self.hub, self.principal, self.domain, kind, params, reason=reason
        )
        return {**_brief(p), "created": created}

    def proposal(self, proposal_id: str) -> dict[str, Any] | None:
        with self.hub.core.engine.connect() as conn:
            try:
                p = proposals.get(conn, proposal_id)
            except Problem:
                return None
        if p.domain != self.domain:
            return None
        return _brief(p)

    def collectors(self) -> list[dict[str, Any]]:
        with self.hub.core.engine.begin() as conn:
            states = collectors.list_all(conn)
        return [
            {
                "collector": s.name,
                "mode": s.mode,
                "consecutive_failures": s.consecutive_failures,
                "last_outcome": (s.last_run or {}).get("outcome"),
                "last_success_at": s.last_success_at,
            }
            for s in states
        ]


def _brief(p: proposals.Proposal) -> dict[str, Any]:
    """Ce qu'un modèle apprend d'une proposition : jamais de quoi l'appliquer lui-même."""
    return {
        "proposal_id": p.id,
        "kind": p.kind,
        "status": p.status,
        "summary": p.preview.get("summary"),
        "created_at": p.created_at,
        "expires_at": p.expires_at,
        "decided_at": p.decided_at,
    }


def call(hub: HubContext, principal: Principal, domain_name: str, name: str, args: Any) -> Any:
    if not isinstance(args, dict):
        raise Problem("validation.params", "arguments : un objet JSON")
    domain = hub.registry.get(domain_name)
    tool = find(principal, domain, name)
    return tool.call(args, Caller(hub, principal, domain_name))
