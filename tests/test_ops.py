"""Chantier S7 : l'exploitation lit les bases dans le registre. La configuration Litestream du
dépôt est celle que `hub ops litestream` écrit ; une restauration remet aussi la base du
domaine factice, et `hub verify` repasse au vert."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import text
from typer.testing import CliRunner

from hub import cli
from hub.core import maintenance, ops
from hub.core.context import HubContext
from hub.core.registry import Registry
from hub.platform.settings import Settings
from tests.support.demo_domain import DemoDomain

ROOT = Path(__file__).resolve().parents[1]


def test_the_repository_litestream_file_is_generated(settings: Settings) -> None:
    hub = HubContext.build(settings)
    try:
        assert ops.database_names(hub) == ["core", "finance"]
        assert (ROOT / "deploy" / "litestream.yml").read_text() == ops.litestream_config(hub)
    finally:
        hub.dispose()


def test_a_mounted_domain_gets_replicated(hub: HubContext) -> None:
    config = ops.litestream_config(hub)
    assert "path: /srv/hub/data/demo.db" in config
    assert "path: /replica/demo.db" in config
    assert ops.database_names(hub) == ["core", "demo"]


def test_ops_commands() -> None:
    out = CliRunner().invoke(cli.app, ["ops", "databases"])
    assert out.exit_code == 0, out.output
    assert out.output.split() == ["core", "finance"]
    assert "dbs:" in CliRunner().invoke(cli.app, ["ops", "litestream"]).output


def test_restore_brings_back_the_demo_domain(settings: Settings, tmp_path: Path) -> None:
    demo = DemoDomain(settings.paths.data)
    hub = HubContext.build(settings, Registry([demo]))
    hub.migrate_all()
    demo.mark_applied("p1", {"seq": 1})
    copies = maintenance.backup_all(hub, tmp_path / "copies", stamp="t")
    assert sorted(p.name for p in copies) == ["core-t.db", "demo-t.db"]
    with demo.engine().begin() as conn:
        conn.execute(text("INSERT INTO items (name) VALUES ('après la copie')"))
    assert maintenance.restore(hub, "t", tmp_path / "copies") == ["core", "demo"]
    with demo.engine().connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM items")).scalar_one() == 0
    report = maintenance.verify(hub)
    assert report.ok, report.checks
    assert report.checks["demo.verify"] == "ok"
    assert demo.applied(["p1"]) == {"p1": {"seq": 1}}
    hub.dispose()
