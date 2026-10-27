"""Lot 7 : commande `hub-brain` (modèle scripté, hub de test) et réglages du brain."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pyrage
import pytest
import yaml
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from hub.brain import cli
from hub.brain.config import BrainConfig, TokenMissing, config, token
from hub.brain.llm import LlmError, Reply
from hub.core import secrets
from hub.core.context import HubContext
from hub.core.settings import Secrets, Settings
from hub.domains.finance.domain import FinanceDomain
from tests.brain.test_brain import Scripted, box_for, calls, last_tool
from tests.finance.test_app_reads import (  # noqa: F401 - fixtures
    client,
    ctx,
    fin,
    year,
)

runner = CliRunner()


class Models(Scripted):
    def __init__(self, *turns: Any, names: list[str] | None = None) -> None:
        super().__init__(*turns)
        self.names = ["qwen3:32b"] if names is None else names

    def models(self) -> list[str]:
        return self.names


def answer_restaurants(amount: str | None = None) -> Any:
    def turn(messages: list[dict[str, Any]]) -> Reply:
        found = amount or next(
            c["amount"]
            for c in last_tool(messages)["by_category"]
            if c["category"] == "restaurants"
        )
        return Reply(f"Tu as dépensé {found} CHF en restaurants ce mois.")

    return turn


@pytest.fixture
def wired(
    monkeypatch: pytest.MonkeyPatch, client: TestClient, ctx: HubContext, year: FinanceDomain
) -> Any:
    def setup(model: Any, which_seen: list[str] | None = None) -> None:
        def toolbox(_cfg: BrainConfig, which: str) -> Any:
            if which_seen is not None:
                which_seen.append(which)
            return box_for(client, ctx, which)

        monkeypatch.setattr(cli, "_toolbox", toolbox)
        monkeypatch.setattr(cli, "_model", lambda _cfg: model)
        monkeypatch.setattr(cli, "_today", lambda: datetime(2026, 10, 27, 9, 0, tzinfo=cli.TZ))
        monkeypatch.setattr(cli, "_cfg", lambda: BrainConfig(state_dir=ctx.settings.paths.data))

    return setup


def test_ask(wired: Any) -> None:
    wired(Models(calls(("finance_month_summary", {})), answer_restaurants()))
    out = runner.invoke(cli.app, ["ask", "combien en restaurants ce mois ?"])
    assert out.exit_code == 0, out.output
    assert "80.00 CHF" in out.output


def test_check_passes_and_fails(wired: Any) -> None:
    wired(Models(calls(("finance_month_summary", {})), answer_restaurants()))
    ok = runner.invoke(cli.app, ["check"])
    assert ok.exit_code == 0, ok.output
    assert "contrôle : ok, la réponse contient 80.00 CHF" in ok.output
    wired(Models(calls(("finance_month_summary", {})), answer_restaurants("95.00")))
    bad = runner.invoke(cli.app, ["check"])
    assert bad.exit_code == 1
    assert "écart" in bad.output
    wired(Models(names=["llama3"]))
    missing = runner.invoke(cli.app, ["check"])
    assert missing.exit_code == 1
    assert "absent" in missing.output


def test_check_without_model(wired: Any) -> None:
    class Down(Models):
        def models(self) -> list[str]:
            raise LlmError("modèle injoignable")

    wired(Down())
    out = runner.invoke(cli.app, ["check"])
    assert out.exit_code == 1
    assert "injoignable" in out.output


def test_suggest_command(wired: Any) -> None:
    wired(Models(*[lambda _m: Reply('{"category": "divers", "reason": "?"}')] * 2))
    out = runner.invoke(cli.app, ["suggest", "--dry-run"])
    assert out.exit_code == 0, out.output
    lines = [json.loads(line) for line in out.output.splitlines()]
    assert lines[-1]["suggested"] == 2
    assert lines[-1]["proposals"] == 0


def test_mcp_command(wired: Any) -> None:
    seen: list[str] = []
    wired(Models(), seen)
    request = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    out = runner.invoke(cli.app, ["mcp", "--token", "aggregates"], input=request + "\n")
    assert out.exit_code == 0, out.output
    assert seen == ["aggregates"]
    tools = json.loads(out.output.splitlines()[-1])["result"]["tools"]
    assert "finance_search" not in {t["name"] for t in tools}
    assert runner.invoke(cli.app, ["mcp", "--token", "app"]).exit_code == 2


def test_ask_when_model_is_down(wired: Any) -> None:
    def down(_m: list[dict[str, Any]]) -> Reply:
        raise LlmError("modèle injoignable")

    wired(Models(down))
    out = runner.invoke(cli.app, ["ask", "?"])
    assert out.exit_code == 1


# --- réglages ---------------------------------------------------------------------------------


def test_config_and_tokens(tmp_path: Path) -> None:
    key = tmp_path / "age.key"
    identity = pyrage.x25519.Identity.generate()
    key.write_text(f"{identity}\n")
    file = tmp_path / "brain.enc.yaml"
    plain = yaml.safe_dump({"brain": {"brain": "hub_b", "aggregates": ""}}).encode()
    file.write_bytes(secrets.encrypt_for(str(identity.to_public()), plain))
    settings = Settings(secrets=Secrets(file=file, age_key_file=key))
    assert token(settings, "brain") == "hub_b"
    with pytest.raises(TokenMissing, match="aggregates"):
        token(settings, "aggregates")
    with pytest.raises(TokenMissing, match="absent"):
        token(Settings(secrets=Secrets(file=tmp_path / "x", age_key_file=key)), "brain")
    file.write_bytes(b"pas chiffr\xe9")
    with pytest.raises(TokenMissing, match="illisibles"):
        token(settings, "brain")
    assert config(settings).model == "qwen3:32b"


def test_toolbox_errors_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "_cfg", lambda: BrainConfig(api_url="http://127.0.0.1:9"))

    def no_token(_settings: Any, _which: str) -> str:
        raise TokenMissing("jeton « brain » absent")

    monkeypatch.setattr(cli, "token", no_token)
    out = runner.invoke(cli.app, ["ask", "?"])
    assert out.exit_code == 2
    assert "absent" in out.output
    monkeypatch.setattr(cli, "token", lambda _s, _w: "hub_x")
    out = runner.invoke(cli.app, ["ask", "?"])
    assert out.exit_code == 1
    assert "hub" in out.output
