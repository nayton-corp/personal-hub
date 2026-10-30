"""Le serveur MCP : les mêmes outils que la boucle, et un geste pour toute la maison refusé sans `confirmed`."""

import asyncio
import json

from mcp.shared.memory import create_connected_server_and_client_session

from domia_assistant.mcp_server import make_server
from domia_assistant.memory import Memory
from domia_assistant.tools import Speaker, build
from tests.fakes import FakeDomia


def test_tools_and_confirmation():
    domia = FakeDomia()
    memory = Memory(":memory:")
    server = make_server(lambda: build(domia, None, memory, None), Speaker(person="robin", client="mcp"))

    async def scenario():
        async with create_connected_server_and_client_session(server) as session:
            names = {t.name for t in (await session.list_tools()).tools}
            assert {"house", "light_command", "set_situation", "remember"} <= names
            refused = await session.call_tool("set_situation", {"value": "AWAY"})
            assert "confirmed" in refused.content[0].text
            await session.call_tool("set_situation", {"value": "AWAY", "confirmed": True})
            house = json.loads((await session.call_tool("house", {})).content[0].text)
            return house

    house = asyncio.run(scenario())
    assert domia.gestures == [("PUT", "/api/situation", {"value": "AWAY"}, "robin")]
    assert house["situation"] == "AWAY"
