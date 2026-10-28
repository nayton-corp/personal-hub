"""Profil de l'instance (chantier « hub générique », G1) : base, API, CLI, fuseau et prompt de
l'assistant. Le pilier 3a selon le pays : tests/finance/test_profile_modules.py."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from hub import cli
from hub.brain import agent
from hub.core import clock, profile
from hub.core.context import HubContext
from hub.core.settings import Settings, get_settings
from tests.conftest import bearer
from tests.finance.test_finance_api import app_session

runner = CliRunner()


def test_existing_base_gets_switzerland_without_name(hub: HubContext) -> None:
    with hub.core.engine.connect() as conn:
        p = profile.get(conn)
    assert (p.display_name, p.country, p.timezone) == (None, "CH", "Europe/Zurich")
    assert p.modules == frozenset({"pillar3a"})


def test_update_validates_and_keeps_other_fields(hub: HubContext) -> None:
    with hub.core.engine.begin() as conn:
        p = profile.update(conn, "system:test", display_name="  Camille   Rey ")
        assert (p.display_name, p.country) == ("Camille Rey", "CH")
        p = profile.update(conn, "system:test", country="fr")
        assert (p.display_name, p.country, p.modules) == ("Camille Rey", "FR", frozenset())
        p = profile.update(conn, "system:test", clear_name=True)
        assert p.display_name is None
        for bad in ({"country": "FRA"}, {"country": "1A"}, {"display_name": "x" * 61}):
            with pytest.raises(profile.ProfileError):
                profile.update(conn, "system:test", **bad)  # type: ignore[arg-type]
        with pytest.raises(profile.ProfileError):
            profile.update(conn, "system:test", display_name="a\x07b")


def test_timezone_comes_from_hub_tz(monkeypatch: pytest.MonkeyPatch, hub: HubContext) -> None:
    monkeypatch.delenv("HUB_TZ", raising=False)
    assert clock.local_tz().key == "Europe/Zurich"
    monkeypatch.setenv("HUB_TZ", "America/Montreal")
    assert clock.local_tz().key == "America/Montreal"
    with hub.core.engine.connect() as conn:
        assert profile.get(conn).timezone == "America/Montreal"


def test_load_without_core_db_gives_default(settings: Settings) -> None:
    assert profile.load(settings) == profile.default()


def test_api_read_by_app_and_tokens_write_by_app_only(
    client: TestClient, hub: HubContext, make_token
) -> None:  # type: ignore[no-untyped-def]
    assert client.get("/api/profile").status_code == 401
    reader = bearer(make_token("demo:read"))
    assert client.get("/api/profile", headers=reader).json() == {
        "display_name": None,
        "country": "CH",
        "timezone": "Europe/Zurich",
        "modules": ["pillar3a"],
    }
    assert client.post("/api/profile", json={"country": "FR"}, headers=reader).status_code == 403
    app_session(hub, client)
    r = client.post("/api/profile", json={"display_name": "Camille", "country": "fr"})
    assert r.status_code == 200
    assert (r.json()["display_name"], r.json()["country"], r.json()["modules"]) == (
        "Camille",
        "FR",
        [],
    )
    # champ absent : inchangé ; prénom vide : effacé
    assert client.post("/api/profile", json={"country": "CH"}).json()["display_name"] == "Camille"
    assert client.post("/api/profile", json={"display_name": ""}).json()["display_name"] is None
    assert client.post("/api/profile", json={"country": "CHE"}).status_code == 422
    assert client.post("/api/profile", json={"plan": "x"}).status_code == 422


def test_capabilities_carry_the_profile(client: TestClient, hub: HubContext, make_token) -> None:  # type: ignore[no-untyped-def]
    with hub.core.engine.begin() as conn:
        profile.update(conn, "system:test", display_name="Camille")
    caps = client.get("/api/tools", headers=bearer(make_token("demo:read"))).json()
    assert caps["profile"]["display_name"] == "Camille"


def test_cli_show_and_set(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HUB_PATHS__DATA", str(tmp_path / "cli-data"))
    get_settings.cache_clear()
    assert runner.invoke(cli.app, ["db", "upgrade"]).exit_code == 0
    out = runner.invoke(cli.app, ["profile", "set", "--name", "Camille", "--country", "be"])
    assert out.exit_code == 0, out.output
    assert json.loads(out.stdout)["country"] == "BE"
    shown = json.loads(runner.invoke(cli.app, ["profile", "show"]).stdout)
    assert (shown["display_name"], shown["modules"]) == ("Camille", [])
    bad = runner.invoke(cli.app, ["profile", "set", "--country", "Belgique"])
    assert bad.exit_code == 2
    get_settings.cache_clear()


def test_system_prompt_uses_the_profile() -> None:
    today = date(2026, 10, 28)
    named = agent.system_prompt(today, {"display_name": "Camille", "country": "CH"})
    assert "assistant financier personnel de Camille, en Suisse." in named
    assert "carte que Camille valide" in named
    anonymous = agent.system_prompt(today, {"country": "XX"})
    assert "de la personne qui utilise ce hub. Nous sommes" in anonymous
    assert "Nathan" not in named + anonymous + agent.system_prompt(today)


def test_no_owner_name_left_in_code() -> None:
    root = Path(__file__).resolve().parents[1]
    hits = [
        str(p.relative_to(root))
        for base in ("hub", "deploy")
        for p in (root / base).rglob("*")
        if p.is_file()
        and p.suffix in {".py", ".js", ".html", ".toml", ".yaml", ".example", ""}
        and "nathan" in p.read_text(errors="ignore").lower()
    ]
    assert hits == []
