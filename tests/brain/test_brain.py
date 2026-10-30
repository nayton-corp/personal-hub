"""Lot 7 : passerelle MCP, routage des outils, assistant et suggestions, contre le vrai hub
(TestClient) et un modèle scripté. Aucun vrai modèle n'est appelé."""

from __future__ import annotations

import io
import json
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient

from hub.brain import agent
from hub.brain.hubapi import HubApi, HubError
from hub.brain.llm import LlmError, OpenAICompatible, Reply, ToolCall, clean
from hub.brain.mcp import McpServer
from hub.brain.suggest import (
    Memory,
    catchup,
    direct,
    for_merchant,
    listing,
    parse_choice,
    suggest,
)
from hub.brain.toolbox import CAPABILITIES, LOAD, Toolbox
from hub.core import proposals
from hub.core.context import HubContext
from hub.domains.finance.domain import FinanceDomain
from tests.finance.test_app_reads import (  # noqa: F401 - fixtures
    client,
    ctx,
    fin,
    year,
)
from tests.finance.test_finance_api import token

TODAY = date(2026, 10, 27)


def bridge(client: TestClient) -> Callable[..., tuple[int, bytes]]:
    def transport(
        method: str, url: str, headers: dict[str, str], data: bytes | None
    ) -> tuple[int, bytes]:
        r = client.request(method, urlsplit(url).path, headers=headers, content=data)
        return r.status_code, r.content

    return transport


def box_for(client: TestClient, ctx: HubContext, which: str, autoload: bool = True) -> Toolbox:
    secret = token(ctx, which)["Authorization"].split()[1]
    box = Toolbox(HubApi("https://hub.example.ts.net", secret, bridge(client)), autoload=autoload)
    box.start()
    return box


class Scripted:
    """Modèle factice : chaque tour est une fonction des messages reçus."""

    def __init__(self, *turns: Callable[[list[dict[str, Any]]], Reply]) -> None:
        self.turns = list(turns)
        self.seen: list[list[dict[str, Any]]] = []
        self.tools: list[list[str]] = []

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        *,
        json_mode: bool = False,
    ) -> Reply:
        self.seen.append(list(messages))
        self.tools.append([t["name"] for t in tools or []])
        return self.turns.pop(0)(messages)


def calls(*items: tuple[str, dict[str, Any]]) -> Callable[[list[dict[str, Any]]], Reply]:
    return lambda _m: Reply("", [ToolCall(f"c{i}", n, a) for i, (n, a) in enumerate(items)])


def last_tool(messages: list[dict[str, Any]]) -> Any:
    return json.loads(next(m for m in reversed(messages) if m["role"] == "tool")["content"])


# --- routage --------------------------------------------------------------------------------


def test_single_domain_is_loaded_at_start(
    client: TestClient, ctx: HubContext, year: FinanceDomain
) -> None:
    box = box_for(client, ctx, "brain=finance")
    names = [t["name"] for t in box.definitions()]
    assert names[:2] == [CAPABILITIES, LOAD]
    assert len(names) == 18  # 2 outils de routage + 16 outils Finance
    agg = box_for(client, ctx, "aggregates")
    assert len(agg.definitions()) == 2 + 7


def test_tools_load_on_demand(client: TestClient, ctx: HubContext, year: FinanceDomain) -> None:
    box = box_for(client, ctx, "brain=finance", autoload=False)
    assert [t["name"] for t in box.definitions()] == [CAPABILITIES, LOAD]
    missing = box.call("finance_month_summary", {})
    assert missing.is_error
    assert LOAD in missing.text
    caps = box.call(CAPABILITIES, {})
    assert caps.data[0]["domain"] == "finance"
    assert caps.data[0]["loaded"] is False
    assert box.call(LOAD, {"domain": "sante"}).is_error
    loaded = box.call(LOAD, {"domain": "finance"})
    assert loaded.tools_changed
    assert "finance_networth" in json.loads(loaded.text)["tools"]
    assert not box.call(LOAD, {"domain": "finance"}).tools_changed
    summary = box.call("finance_month_summary", {"month": "2026-10"})
    assert not summary.is_error
    assert summary.data["month"] == "2026-10"
    refused = box.call("finance_month_summary", {"month": "2027-01"})
    assert refused.is_error
    assert json.loads(refused.text)["error"] == "validation.params"


def test_hub_errors() -> None:
    def down(*_a: Any) -> tuple[int, bytes]:
        raise OSError("refused")

    with pytest.raises(HubError) as exc:
        HubApi("http://api:8710", "hub_x", down).capabilities()
    assert exc.value.type == "hub.unreachable"
    with pytest.raises(HubError) as exc:
        HubApi("http://api:8710", "hub_x", lambda *_a: (401, b"{}")).capabilities()
    assert exc.value.type == "http_401"


# --- MCP --------------------------------------------------------------------------------------


def rpc(server: McpServer, method: str, msg_id: int = 1, **params: Any) -> list[dict[str, Any]]:
    return server.handle({"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params})


def test_mcp_session(client: TestClient, ctx: HubContext, year: FinanceDomain) -> None:
    server = McpServer(box_for(client, ctx, "aggregates", autoload=False))
    (init,) = rpc(server, "initialize", protocolVersion="2025-03-26", capabilities={})
    assert init["result"]["protocolVersion"] == "2025-03-26"
    assert init["result"]["capabilities"]["tools"]["listChanged"] is True
    assert server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) == []
    assert rpc(server, "ping")[0]["result"] == {}
    (listed,) = rpc(server, "tools/list")
    assert [t["name"] for t in listed["result"]["tools"]] == [CAPABILITIES, LOAD]
    _reply, note = rpc(server, "tools/call", name=LOAD, arguments={"domain": "finance"})
    assert note == {"jsonrpc": "2.0", "method": "notifications/tools/list_changed"}
    (listed,) = rpc(server, "tools/list")
    tools = {t["name"]: t for t in listed["result"]["tools"]}
    assert "finance_search" not in tools  # jeton agrégats
    assert tools["finance_networth"]["inputSchema"]["type"] == "object"
    (called,) = rpc(server, "tools/call", name="finance_networth", arguments={})
    body = json.loads(called["result"]["content"][0]["text"])
    assert called["result"]["isError"] is False
    assert "net_worth" in body
    (denied,) = rpc(server, "tools/call", name="finance_search", arguments={"query": "abc"})
    assert denied["result"]["isError"] is True
    assert rpc(server, "resources/list")[0]["error"]["code"] == -32601
    assert rpc(server, "tools/call", name=3)[0]["error"]["code"] == -32602
    assert server.handle([1])[0]["error"]["code"] == -32600
    (old,) = rpc(server, "initialize", protocolVersion="1999-01-01")
    assert old["result"]["protocolVersion"] == "2025-06-18"


def test_mcp_over_stdio(client: TestClient, ctx: HubContext, year: FinanceDomain) -> None:
    server = McpServer(box_for(client, ctx, "brain=finance"))
    lines = [
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}),
        "",
        "pas du json",
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "finance_month_summary", "arguments": {}},
            }
        ),
    ]
    out = io.StringIO()
    server.serve(lines, out)
    replies = [json.loads(line) for line in out.getvalue().splitlines()]
    assert [r.get("id") for r in replies] == [1, None, 2]
    assert replies[1]["error"]["code"] == -32700
    text = replies[2]["result"]["content"][0]["text"]
    assert '"restaurants"' in text
    assert '"80.00"' in text


# --- assistant ----------------------------------------------------------------------------------


def test_restaurants_this_month(client: TestClient, ctx: HubContext, year: FinanceDomain) -> None:
    """La question de sortie du lot 7, avec un modèle qui suit les outils."""

    def answer(messages: list[dict[str, Any]]) -> Reply:
        summary = last_tool(messages)
        resto = next(c for c in summary["by_category"] if c["category"] == "restaurants")
        return Reply(f"Ce mois, {resto['amount']} CHF en restaurants.")

    model = Scripted(
        calls(("finance_list_categories", {})),
        calls(("finance_month_summary", {})),
        answer,
    )
    out = agent.ask(
        "Combien en restaurants ce mois ?", box_for(client, ctx, "brain=finance"), model, TODAY
    )
    assert out.text == "Ce mois, 80.00 CHF en restaurants."
    assert out.tools == ["finance_list_categories", "finance_month_summary"]
    system = model.seen[0][0]["content"]
    assert "2026-10-27" in system
    assert "écrits par des tiers" in system
    assert "finance_propose_category" in model.tools[0]


def test_accepted_suggestion_goes_through_a_card(
    client: TestClient, ctx: HubContext, year: FinanceDomain
) -> None:
    def propose(messages: list[dict[str, Any]]) -> Reply:
        entry = last_tool(messages)["items"][0]["entry_id"]
        return calls(("finance_propose_category", {"entry_id": entry, "category": "loisirs"}))(
            messages
        )

    model = Scripted(
        calls(("finance_search", {"query": "kiosque"})),
        propose,
        lambda _m: Reply("<think>simple</think>Carte créée, à valider dans l'app."),
    )
    out = agent.ask(
        "Le kiosque, c'est des loisirs", box_for(client, ctx, "brain=finance"), model, TODAY
    )
    assert out.text == "<think>simple</think>Carte créée, à valider dans l'app."  # pas de clean ici
    (pid,) = out.proposals
    with ctx.core.engine.connect() as conn:
        p = proposals.get(conn, pid)
    assert (p.status, p.tier, p.kind) == ("pending", "human", "recategorize")


def test_agent_gives_up(client: TestClient, ctx: HubContext, year: FinanceDomain) -> None:
    model = Scripted(*[calls((CAPABILITIES, {}))] * 3)
    out = agent.ask("?", box_for(client, ctx, "brain=finance"), model, TODAY, max_steps=3)
    assert out.complete is False
    assert out.tools == [CAPABILITIES] * 3


# --- suggestions ------------------------------------------------------------------------------


def test_parse_choice() -> None:
    allowed = {"loisirs", "divers"}
    assert parse_choice('ok {"category": "loisirs", "reason": "un\\nkiosque"} fin', allowed) == (
        "loisirs",
        "un kiosque",
    )
    assert parse_choice('{"category": "casino", "reason": "x"}', allowed) == (None, "x")
    assert parse_choice('{"category": null}', allowed) == (None, "")
    assert parse_choice("rien", allowed) == (None, "")
    assert parse_choice("{pas json}", allowed) == (None, "")
    assert parse_choice("[1]", allowed) == (None, "")
    # pas sûr : rien, même avec une catégorie de la liste
    assert parse_choice('{"category": "loisirs", "sure": false, "reason": "x"}', allowed) == (
        None,
        "x",
    )


def test_prompt_guides_the_model() -> None:
    cats = [
        {"id": "transports", "name": "Transports", "group": "variable"},
        {"id": "twint-particuliers", "name": "TWINT entre particuliers", "group": "variable"},
    ]
    assert "pas les commerces" not in listing(cats)
    assert "carburant" in listing(cats)
    shop = [c["id"] for c in for_merchant(cats, "debit twint zorglub shop")]
    assert shop == ["transports"]
    assert len(for_merchant(cats, "debit twint dupont, jean")) == 2


def merchant(prompt: str) -> str:
    return prompt.split("<commercant>")[1].split("</commercant>")[0]


def test_suggest_for_unknown_merchants(
    client: TestClient, ctx: HubContext, year: FinanceDomain, tmp_path: Path
) -> None:
    def choose(messages: list[dict[str, Any]]) -> Reply:
        prompt = messages[0]["content"]
        assert "<commercant>" in prompt
        assert "loisirs" in prompt
        if "kiosque" in merchant(prompt):
            return Reply('{"category": "loisirs", "reason": "Un kiosque."}')
        return Reply('{"category": null, "reason": "incertain"}')

    box = box_for(client, ctx, "brain=finance")
    memory = Memory(tmp_path / "brain")
    report = suggest(box, Scripted(choose, choose), memory)
    assert (report.merchants, report.suggested, report.proposals, report.skipped) == (2, 1, 1, 1)
    with ctx.core.engine.connect() as conn:
        (p,) = proposals.list_by_status(conn, "pending")
    assert p.reason == "Un kiosque."
    assert p.params["suggested"] is True
    # déjà suggérée : rien de nouveau au passage suivant, même après un refus
    again = suggest(box, Scripted(choose), Memory(tmp_path / "brain"))
    assert (again.merchants, again.proposals) == (1, 0)
    dry = suggest(box, Scripted(choose), Memory(tmp_path / "other"), dry_run=True, groups=1)
    assert dry.suggested == 1
    assert dry.proposals == 0


def test_suggest_stops_cleanly(
    client: TestClient, ctx: HubContext, year: FinanceDomain, tmp_path: Path
) -> None:
    def down(_m: list[dict[str, Any]]) -> Reply:
        raise LlmError("modèle injoignable")

    report = suggest(box_for(client, ctx, "brain=finance"), Scripted(down), Memory(tmp_path))
    assert report.stopped == "modèle injoignable"
    assert report.proposals == 0
    from hub.platform.settings import Auth

    ctx.settings = ctx.settings.model_copy(update={"auth": Auth(token_proposals_per_hour=1)})
    box = box_for(client, ctx, "brain=finance")
    box.call("finance_propose_budget", {"category": "divers", "amount": "1"})
    report = suggest(
        box, Scripted(lambda _m: Reply('{"category": "divers", "reason": "x"}')), Memory(tmp_path)
    )
    assert report.stopped == "limite de propositions par heure atteinte"


class Every:
    """Modèle factice qui répond à chaque appel avec la même fonction."""

    def __init__(self, turn: Callable[[list[dict[str, Any]]], Reply]) -> None:
        self.turn = turn
        self.prompts: list[str] = []

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        *,
        json_mode: bool = False,
    ) -> Reply:
        self.prompts.append(messages[0]["content"])
        return self.turn(messages)


def test_catchup_proposes_one_rule_per_merchant(
    client: TestClient, ctx: HubContext, year: FinanceDomain, tmp_path: Path
) -> None:
    def choose(messages: list[dict[str, Any]]) -> Reply:
        if "kiosque" in merchant(messages[0]["content"]):
            return Reply('{"category": "loisirs", "reason": "Un kiosque."}')
        return Reply('{"category": null, "reason": "incertain"}')

    box = box_for(client, ctx, "brain=finance")
    model = Every(choose)
    report = catchup(box, model, Memory(tmp_path / "brain"))
    assert report.merchants == len(model.prompts) >= 2
    assert (report.suggested, report.proposals) == (1, 1)
    with ctx.core.engine.connect() as conn:
        (p,) = proposals.list_by_status(conn, "pending")
    # une règle (pas une carte par écriture), avant les packs et la règle « tout le reste »
    assert p.kind == "create_rule"
    assert "kiosque" in p.params["pattern"]
    assert (p.params["direction"], p.params["priority"]) == ("debit", 10)
    assert p.reason == "Un kiosque."
    # proposée une fois : le passage suivant ne la redemande pas
    again = Every(choose)
    catchup(box, again, Memory(tmp_path / "brain"))
    assert not [x for x in again.prompts if "kiosque" in merchant(x)]
    dry = catchup(box, Every(choose), Memory(tmp_path / "dry"), dry_run=True, limit=1)
    assert (dry.merchants, dry.proposals) == (1, 0)


def test_direct_groups_one_off_purchases_by_category(
    client: TestClient, ctx: HubContext, year: FinanceDomain, tmp_path: Path
) -> None:
    def choose(messages: list[dict[str, Any]]) -> Reply:
        if "kiosque" in merchant(messages[0]["content"]):
            return Reply('{"category": "alimentation", "sure": true, "reason": "Un kiosque."}')
        return Reply('{"category": null, "sure": false, "reason": "incertain"}')

    box = box_for(client, ctx, "brain=finance")
    model = Every(choose)
    report = direct(box, model, Memory(tmp_path / "brain"), max_count=5)
    assert report.merchants == len(model.prompts) >= 1
    assert (report.suggested, report.proposals) == (1, 1)
    with ctx.core.engine.connect() as conn:
        (p,) = proposals.list_by_status(conn, "pending")
    # une carte par catégorie, sans règle
    assert p.kind == "categorize_entries"
    assert p.params["category_id"] == "alimentation"
    assert p.params["suggested"] is True
    assert p.preview["details"]["count"] == len(p.params["entry_ids"])
    # ni le commerçant proposé ni l'incertain ne sont redemandés
    again = Every(choose)
    assert direct(box, again, Memory(tmp_path / "brain"), max_count=5).merchants == 0
    # par défaut, seulement les commerçants vus une fois
    dry = direct(box, Every(choose), Memory(tmp_path / "dry"), dry_run=True)
    assert dry.proposals == 0


# --- client du modèle -------------------------------------------------------------------------


def test_openai_compatible_client() -> None:
    sent: list[tuple[str, str, Any]] = []

    def transport(
        method: str, url: str, headers: dict[str, str], data: bytes | None
    ) -> tuple[int, bytes]:
        sent.append((method, url, json.loads(data) if data else None))
        if url.endswith("/models"):
            return 200, json.dumps({"data": [{"id": "qwen3:32b"}]}).encode()
        message = {
            "role": "assistant",
            "content": "<think>je réfléchis</think>",
            "tool_calls": [
                {"id": "a", "function": {"name": "finance_networth", "arguments": "{}"}},
                {"function": {"name": "finance_search", "arguments": {"query": "migros"}}},
                {"function": {"name": "x", "arguments": "{pas json"}},
                "bruit",
            ],
        }
        return 200, json.dumps({"choices": [{"message": message}]}).encode()

    llm = OpenAICompatible("http://host.docker.internal:11434/v1/", "qwen3:32b", 30, transport)
    assert llm.models() == ["qwen3:32b"]
    reply = llm.chat(
        [{"role": "user", "content": "?"}],
        [{"name": "t", "description": "d", "input_schema": {"type": "object"}}],
        json_mode=True,
    )
    assert reply.content == ""
    assert [(c.id, c.name, c.arguments) for c in reply.tool_calls] == [
        ("a", "finance_networth", {}),
        ("call_1", "finance_search", {"query": "migros"}),
        ("call_2", "x", {}),
    ]
    method, url, body = sent[-1]
    assert (method, url) == ("POST", "http://host.docker.internal:11434/v1/chat/completions")
    assert body["tools"][0]["function"]["parameters"] == {"type": "object"}
    assert body["response_format"] == {"type": "json_object"}
    assert body["temperature"] == 0
    assert clean("a<think>\nb\n</think> c") == "a c"


@pytest.mark.parametrize(
    ("status", "raw", "message"),
    [
        (500, b"", "HTTP 500"),
        (200, b"pas du json", "illisible"),
        (200, b'{"choices": []}', "sans message"),
    ],
)
def test_openai_compatible_errors(status: int, raw: bytes, message: str) -> None:
    llm = OpenAICompatible("http://llm/v1", "m", 30, lambda *_a: (status, raw))
    with pytest.raises(LlmError, match=message):
        llm.chat([])


def test_llm_unreachable() -> None:
    def down(*_a: Any) -> tuple[int, bytes]:
        raise OSError("refused")

    with pytest.raises(LlmError, match="injoignable"):
        OpenAICompatible("http://llm/v1", "m", 30, down).models()
