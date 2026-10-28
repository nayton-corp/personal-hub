"""Catalogue des connecteurs (chantier « hub générique », G3) : une seule déclaration, que le
cœur, les conteneurs, compose et le code des collecteurs respectent."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from hub.collectors import base, runtime
from hub.core import connectors, cron
from hub.core.context import HubContext
from tests.finance.test_finance_api import app_session

ROOT = Path(__file__).resolve().parents[1]
SECRET = re.compile(r"env\.secret\(\"([a-z_]+)\"\)")


def test_one_flow_per_connector() -> None:
    assert connectors.NAMES == base.NAMES
    assert set(runtime.flows()) == set(connectors.NAMES)
    assert {c.runner for c in connectors.CATALOG} == set(connectors.RUNNERS)
    assert [c.name for c in connectors.CATALOG if c.runner == "browser"] == ["bcf", "viac"]


def test_entries_are_well_formed() -> None:
    for c in connectors.CATALOG:
        assert c.method in connectors.METHODS, c.name
        assert c.country is None or re.fullmatch(r"[A-Z]{2}", c.country), c.name
        assert set(c.accounts) <= {"cash", "pension", "securities", "crypto"}, c.name
        assert c.formats, c.name
        assert set(c.required) <= set(c.settings), c.name
        job = cron.parse(f"{c.schedule} true")[0]
        assert job.due(datetime(2026, 1, 1)) in (True, False)


def test_one_compose_service_per_runner() -> None:
    compose = (ROOT / "deploy" / "compose.yaml").read_text()
    services = set(re.findall(r"^  collector-([a-z0-9]+):", compose, re.M))
    assert services == set(connectors.RUNNERS)
    for runner in connectors.RUNNERS:
        assert f"HUB_COLLECTOR_RUNNER: {runner}" in compose


def test_declared_secrets_match_the_flows() -> None:
    for c in connectors.CATALOG:
        folder = ROOT / "hub" / "collectors"
        package = {"enable_banking": "revolut"}.get(c.name, c.name)  # premier usage : Revolut
        code = folder / package if (folder / package).is_dir() else folder / "exchanges"
        files = code.glob("*.py") if code.name == package else [code / f"{c.name}.py"]
        used = {m for f in files for m in SECRET.findall(f.read_text())}
        assert used == set(c.secrets), c.name


def test_connection_settings_complete_the_service_config() -> None:
    cfg = base.CollectorConfig()
    n26 = base.for_connection(cfg, "enable_banking", {"aspsp_name": "N26", "aspsp_country": "DE"})
    assert (n26.revolut.aspsp_name, n26.revolut.aspsp_country) == ("N26", "DE")
    assert n26.revolut.api_url == cfg.revolut.api_url
    market = base.for_connection(cfg, "market", {"currencies": ["EUR"], "quotes": {"X": "X.SW"}})
    assert (market.market.currencies, market.market.quotes) == (["EUR"], {"X": "X.SW"})
    assert base.for_connection(cfg, "bcf", {}) is cfg
    with pytest.raises(ValidationError):
        base.for_connection(cfg, "enable_banking", {"max_syncs_per_day": 9})
    for c in connectors.CATALOG:  # chaque réglage déclaré existe dans sa section
        section = base.SECTIONS.get(c.name)
        fields = type(getattr(cfg, section)).model_fields if section else {}
        assert set(c.settings) <= set(fields), c.name
    old = base.config(type("S", (), {"domain": lambda _s, _n: {"schedules": {"bcf": "x"}}})())  # type: ignore[arg-type]
    assert old == cfg  # les horaires d'avant G4 sont ignorés


def test_catalog_route_is_for_the_app(client: TestClient, hub: HubContext, make_token) -> None:  # type: ignore[no-untyped-def]
    path = "/api/collectors/catalog"
    assert (
        client.get(path, headers={"Authorization": f"Bearer {make_token('demo:read')}"}).status_code
        == 403
    )
    app_session(hub, client)
    items = client.get(path).json()["items"]
    assert [i["name"] for i in items] == list(connectors.NAMES)
    assert items[0] == connectors.CATALOG[0].public()
