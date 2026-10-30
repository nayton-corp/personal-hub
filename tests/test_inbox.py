"""Chantier S4 : la boîte d'entrée confie chaque fichier au domaine qui le réclame ; un fichier
pour le domaine factice n'atteint jamais la finance ; les collecteurs déposent dans
`inbox/<domaine>/` et l'archive d'avant passe sous `archive/finance/`."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import text
from typer.testing import CliRunner

from hub import cli, cli_inbox
from hub.collectors import cli as collectors_cli
from hub.collectors.runtime import Assigned
from hub.core import connectors, inbox
from hub.core.registry import Registry
from hub.domains.finance.domain import FinanceDomain
from hub.platform.settings import Settings
from tests.support.demo_domain import DemoDomain


def _drop(folder: Path, name: str, data: bytes, age: float = 10) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_bytes(data)
    past = time.time() - age
    os.utime(path, (past, past))
    return path


def test_each_file_goes_to_the_domain_that_claims_it(settings: Settings) -> None:
    demo = DemoDomain(settings.paths.data, settings.paths.inbox_of("demo"))
    finance = FinanceDomain(settings)
    registry = Registry([demo, finance])
    root = settings.paths.inbox
    _drop(root, "idee.demo", b"x")
    _drop(root, "note.txt", b"DEMO 1")
    _drop(root, "releve.xml", b"<?xml version='1.0'?>")
    _drop(root, "photo.heic", b"")
    _drop(root, "fresh.demo", b"", age=0)  # encore en copie : il attend
    _drop(root / "finance", "releve.xml", b"deja la")  # même nom : pas d'écrasement
    routed = inbox.route(registry, root)
    assert routed.moved == {"demo": 2, "finance": 1}
    assert routed.waiting == 1
    assert sorted(p.name for p in root.iterdir() if p.is_file()) == ["fresh.demo", "photo.heic"]
    assert sorted(p.name for p in (root / "demo").iterdir()) == ["idee.demo", "note.txt"]
    assert sorted(p.name for p in (root / "finance").iterdir()) == ["releve-2.xml", "releve.xml"]
    assert inbox.route(registry, root / "absent").public() == {"moved": {}, "waiting": 0}


def test_a_demo_file_never_reaches_finance(settings: Settings) -> None:
    demo = DemoDomain(settings.paths.data, settings.paths.inbox_of("demo"))
    demo.migrate()
    finance = FinanceDomain(settings)
    finance.migrate()
    registry = Registry([demo, finance])
    _drop(settings.paths.inbox, "idee.demo", b"x")
    inbox.route(registry, settings.paths.inbox)
    assert finance.process_inbox()["files"] == 0
    assert demo.process_inbox() == {"files": 1}
    with demo.engine().connect() as conn:
        assert conn.execute(text("SELECT name FROM items")).scalars().all() == ["idee.demo"]
    finance.engine().dispose()


def test_watch_inbox_routes_then_lets_each_domain_work(
    settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    demo = DemoDomain(settings.paths.data, settings.paths.inbox_of("demo"))
    demo.migrate()
    hub = SimpleNamespace(registry=Registry([demo]), settings=settings)
    _drop(settings.paths.inbox, "a.demo", b"x")
    cli_inbox.watch(lambda: hub)(poll=1, once=True)  # type: ignore[arg-type, return-value]
    assert json.loads(capsys.readouterr().out) == {
        "moved": {"demo": 1},
        "waiting": 0,
        "domains": {"demo": {"files": 1}},
    }
    assert "watch-inbox" in CliRunner().invoke(cli.app, ["--help"]).output


def test_collectors_drop_into_their_domain_folder(settings: Settings, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    assert {c.domain for c in connectors.catalog()} == {"finance"}
    monkeypatch.setattr(collectors_cli, "get_settings", lambda: settings)
    item = Assigned("bcf", "bcf", "BCF", None, {}, None)
    env = collectors_cli.env_for(item, None)
    assert env.inbox_root == settings.paths.inbox / "finance"


def test_the_archive_of_before_moves_under_finance(settings: Settings) -> None:
    old = settings.paths.archive
    _drop(old / "2026" / "10", "x.age", b"a")
    _drop(old / "duplicates", "y.age", b"b")
    _drop(old, "autre", b"c")
    finance = FinanceDomain(settings)
    finance.migrate()
    assert (old / "finance" / "2026" / "10" / "x.age").read_bytes() == b"a"
    assert (old / "finance" / "duplicates" / "y.age").exists()
    assert (old / "autre").exists()  # pas à la finance : il reste
    finance.migrate()  # relancé : rien ne bouge
    assert sorted(p.name for p in old.iterdir()) == ["autre", "finance"]
    finance.engine().dispose()
