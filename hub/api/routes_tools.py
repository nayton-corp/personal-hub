"""Routes des outils de l'assistant (lot 7) : la passerelle MCP du Mac les relaie.

`GET /api/tools` décrit les domaines ouverts au jeton (`hub_capabilities`), `GET
/api/tools/{domaine}` donne leurs outils, `POST /api/tools/{domaine}/{outil}` en appelle un.
Réservées aux jetons : l'app a ses propres routes.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, Path

from hub.api.schemas import CapabilitiesOut, ToolCallOut, ToolOut, ToolsOut
from hub.core import tools
from hub.core.auth import Ctx, CurrentPrincipal, Principal
from hub.core.errors import Problem

router = APIRouter(tags=["outils"])
NAME = r"^[a-z][a-z0-9_]{1,63}$"


def _token(principal: CurrentPrincipal) -> Principal:
    if principal.is_app:
        raise Problem("auth.scope", "réservé aux jetons de l'assistant")
    return principal


Token = Annotated[Principal, Depends(_token)]


@router.get("/tools", response_model=CapabilitiesOut)
def capabilities(hub_ctx: Ctx, principal: Token) -> CapabilitiesOut:
    return CapabilitiesOut.model_validate({"domains": tools.capabilities(hub_ctx, principal)})


@router.get("/tools/{domain}", response_model=ToolsOut)
def domain_tools(
    hub_ctx: Ctx, principal: Token, domain: Annotated[str, Path(pattern=NAME)]
) -> ToolsOut:
    found = tools.visible_tools(principal, hub_ctx.registry.get(domain))
    if not found:
        raise Problem("auth.scope")
    return ToolsOut(
        domain=domain,
        items=[
            ToolOut(name=t.name, description=t.description, input_schema=t.input_schema)
            for t in found
        ],
    )


@router.post("/tools/{domain}/{name}", response_model=ToolCallOut)
def call_tool(
    hub_ctx: Ctx,
    principal: Token,
    domain: Annotated[str, Path(pattern=NAME)],
    name: Annotated[str, Path(pattern=NAME)],
    args: Annotated[dict[str, Any] | None, Body()] = None,
) -> ToolCallOut:
    return ToolCallOut(result=tools.call(hub_ctx, principal, domain, name, args or {}))
