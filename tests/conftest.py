from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hub.api.app import create_app
from hub.core import tokens
from hub.core.context import HubContext
from hub.core.registry import Registry
from hub.platform import logging as hub_logging
from hub.platform.settings import Paths, Server, Settings
from tests.support.demo_domain import DemoDomain


@pytest.fixture(autouse=True)
def _isolated_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # aucun fichier /etc/hub de la machine ne doit influencer un test
    monkeypatch.setenv("HUB_SETTINGS", str(tmp_path / "absent.toml"))
    hub_logging.configure("INFO")


def make_settings(tmp_path: Path, origin: str = "https://hub.example.ts.net") -> Settings:
    return Settings(
        paths=Paths(
            data=tmp_path / "data",
            inbox=tmp_path / "inbox",
            archive=tmp_path / "archive",
            backup=tmp_path / "backup",
        ),
        server=Server(public_origin=origin),
    )


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return make_settings(tmp_path)


@pytest.fixture
def demo(settings: Settings) -> DemoDomain:
    return DemoDomain(settings.paths.data)


@pytest.fixture
def hub(settings: Settings, demo: DemoDomain) -> Iterator[HubContext]:
    ctx = HubContext.build(settings, Registry([demo]))
    ctx.migrate_all()
    yield ctx
    ctx.dispose()


@pytest.fixture
def client(hub: HubContext) -> Iterator[TestClient]:
    with TestClient(create_app(hub), base_url="https://hub.example.ts.net") as c:
        yield c


@pytest.fixture
def make_token(hub: HubContext):  # type: ignore[no-untyped-def]
    def _make(*scopes: str, name: str = "test") -> str:
        with hub.core.engine.begin() as conn:
            _info, secret = tokens.create(conn, name, list(scopes), "system:test", days=30)
        return secret

    return _make


def bearer(secret: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {secret}"}


def add_connections(hub: HubContext, *names: str) -> None:
    """Les connexions d'avant G4 (bcf, revolut…), sans secret : leur état existe."""
    from hub.core import connections
    from hub.domains.finance.sources.app.legacy_connections import LEGACY

    with hub.core.engine.begin() as conn:
        for name in names or tuple(LEGACY):
            connector, label = LEGACY[name]
            settings = {"aspsp_name": "Revolut", "aspsp_country": "LT"} if name == "revolut" else {}
            connections.create(conn, name, connector, "system:test", label=label, settings=settings)
