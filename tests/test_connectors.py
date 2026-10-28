"""Catalogue des connecteurs (chantier « hub générique », G3) : une seule déclaration, que le
cœur, les conteneurs, compose et le code des collecteurs respectent."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient

from hub.collectors import base, runtime
from hub.core import collectors, connectors, cron
from hub.core.context import HubContext
from tests.finance.test_finance_api import app_session

ROOT = Path(__file__).resolve().parents[1]
SECRET = re.compile(r"env\.secret\(\"([a-z_]+)\"\)")


def test_one_list_of_collectors() -> None:
    assert connectors.NAMES == base.NAMES == tuple(collectors.COLLECTORS)
    assert set(runtime.flows()) == set(connectors.NAMES)
    assert collectors.COLLECTORS["revolut"] == "Revolut"


def test_entries_are_well_formed() -> None:
    for c in connectors.CATALOG:
        assert c.method in connectors.METHODS, c.name
        assert c.country is None or re.fullmatch(r"[A-Z]{2}", c.country), c.name
        assert set(c.accounts) <= {"cash", "pension", "securities", "crypto"}, c.name
        assert c.formats, c.name
        job = cron.parse(f"{c.schedule} true")[0]
        assert job.due(datetime(2026, 1, 1)) in (True, False)


def test_each_collector_has_its_compose_service() -> None:
    compose = (ROOT / "deploy" / "compose.yaml").read_text()
    services = set(re.findall(r"^  collector-([a-z0-9]+):", compose, re.M))
    assert services == set(connectors.NAMES)


def test_declared_secrets_match_the_flows() -> None:
    for c in connectors.CATALOG:
        folder = ROOT / "hub" / "collectors"
        code = folder / c.name if (folder / c.name).is_dir() else folder / "exchanges"
        files = code.glob("*.py") if code.name == c.name else [code / f"{c.name}.py"]
        used = {m for f in files for m in SECRET.findall(f.read_text())}
        assert used == set(c.secrets), c.name


def test_schedules_default_to_the_catalog_and_override_one_by_one() -> None:
    assert base.CollectorConfig().schedules == connectors.schedules()
    cfg = base.CollectorConfig.model_validate({"schedules": {"bcf": "0 8 * * 1-5"}})
    assert cfg.schedules["bcf"] == "0 8 * * 1-5"
    assert cfg.schedules["viac"] == connectors.get("viac").schedule  # type: ignore[union-attr]


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
