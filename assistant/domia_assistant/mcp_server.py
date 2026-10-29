"""Le serveur MCP (spec §6) : les mêmes outils que la boucle, au protocole MCP sur stdio. Il sert au banc (Claude
Desktop, référence jouée à la main, décision 4) et à tout client MCP. La personne pour qui il parle se règle au
lancement (`--person`), comme l'appareil qui parle à POST /talk ; les gestes qui touchent toute la maison demandent
`confirmed: true`, que le client n'envoie qu'après le oui de la personne."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable

from .tools import Speaker, Toolbox


def make_server(toolbox: Callable[[], Toolbox], who: Speaker):
    import mcp.types as types
    from mcp.server.lowlevel import Server

    server = Server("domia-assistant")

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        out = []
        for tool in toolbox().tools.values():
            schema = json.loads(json.dumps(tool.parameters))
            if tool.gesture:
                schema["properties"]["confirmed"] = {
                    "type": "boolean",
                    "description": "true seulement après le oui de la personne, pour un geste qui touche toute la maison",
                }
            out.append(types.Tool(name=tool.name, description=tool.description, inputSchema=schema))
        return out

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
        box = toolbox()
        tool = box.get(name)
        args = dict(arguments or {})
        confirmed = bool(args.pop("confirmed", False))
        if tool is not None and tool.gesture and tool.house_wide(args) and not confirmed:
            result = {
                "error": "geste pour toute la maison : demande d'abord à la personne, puis rappelle avec confirmed: true"
            }
        else:
            result = box.run(name, args, who)
        return [types.TextContent(type="text", text=json.dumps(result, ensure_ascii=False, default=str))]

    return server


def run(toolbox: Callable[[], Toolbox], who: Speaker) -> None:
    import mcp.server.stdio

    server = make_server(toolbox, who)

    async def main() -> None:
        async with mcp.server.stdio.stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())

    asyncio.run(main())
