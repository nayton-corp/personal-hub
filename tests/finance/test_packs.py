"""Packs de règles de départ (chantier « hub générique », G2)."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import text
from typer.testing import CliRunner

from hub.core import profile
from hub.core.coredb import CoreDB
from hub.domains.finance.classement.app import packs, rules
from hub.domains.finance.domain import FinanceDomain
from hub.platform.db import begin_immediate
from hub.platform.settings import Settings
from tests.finance.conftest import rows

# lieux et comptes de l'ancien script personnel : jamais dans un pack livré
PERSONAL = ("fribourg", "fri-son", "aigle noir", "le port", "wielandbus", "tpf", "raiffeisen")


def pack_ids(finance: FinanceDomain, name: str) -> set[str]:
    return {str(r[0]) for r in rows(finance, f"SELECT id FROM rules WHERE id LIKE 'pack-{name}-%'")}


def test_shipped_packs_are_valid_and_neutral() -> None:
    found = packs.available()
    assert set(found) == {"base", "ch"}
    assert found["ch"].country == "CH"
    assert found["base"].country is None
    for p in found.values():
        words = " ".join(kw for g in p.groups for kw in g.keywords)
        assert not [w for w in PERSONAL if w in words], p.name
        cats = {c.id for c in p.categories}
        assert {g.category for g in p.groups} <= cats
        assert len(p.specs()) == len({s[:4] for s in p.specs()})
    assert [p.name for p in packs.defaults_for("CH")] == ["base", "ch"]
    assert [p.name for p in packs.defaults_for("FR")] == ["base"]


def test_fresh_base_follows_the_profile_country(fsettings: Settings) -> None:
    core = CoreDB.from_settings(fsettings)
    core.migrate()
    with core.engine.begin() as conn:
        profile.update(conn, "system:test", country="FR")
    core.dispose()
    domain = FinanceDomain(fsettings)
    domain.migrate()
    with domain.engine().connect() as conn:
        assert packs.installed(conn) == {"base": packs.available()["base"].version}
    # une base existante ne reçoit rien de plus à la migration suivante
    domain.migrate()
    assert rows(domain, "SELECT count(*) FROM rule_packs") == [(1,)]
    domain.engine().dispose()


def test_install_update_and_user_choices(finance: FinanceDomain) -> None:
    ch = packs.available()["ch"]
    before = pack_ids(finance, "ch")
    some = sorted(before)[0]
    with begin_immediate(finance.engine()) as conn:
        rules.set_active(conn, some, False)
        # même pack réinstallé : rien d'ajouté, la règle coupée le reste
        again = packs.install(conn, ch)
    assert (again.added, again.kept, again.disabled) == (0, len(before), 0)
    assert rows(finance, f"SELECT active FROM rules WHERE id = '{some}'") == [(0,)]

    # version suivante : un mot en moins, un mot en plus
    groups = list(ch.groups)
    first = groups[0]
    dropped = first.keywords[0]
    groups[0] = packs.Group(
        first.category, first.direction, first.priority, (*first.keywords[1:], "zorglub")
    )
    v2 = packs.Pack(
        ch.name, ch.version + 1, ch.label, ch.description, ch.country, ch.categories, tuple(groups)
    )
    with begin_immediate(finance.engine()) as conn:
        dry = packs.install(conn, v2, dry_run=True)
        assert (dry.added, dry.disabled, dry.dry_run) == (1, 1, True)
        assert packs.installed(conn)["ch"] == ch.version
        done = packs.install(conn, v2)
        assert (done.added, done.disabled) == (1, 1)
        assert packs.installed(conn)["ch"] == ch.version + 1
    gone = ch.rule_id(
        "search_text",
        rules.normalize_pattern("search_text", dropped),
        first.direction,
        first.category,
    )
    assert rows(finance, f"SELECT active FROM rules WHERE id = '{gone}'") == [(0,)]


def test_same_rule_from_another_origin_is_not_doubled(finance: FinanceDomain) -> None:
    with begin_immediate(finance.engine()) as conn:
        conn.execute(text("DELETE FROM rule_packs"))
        first = packs.install(conn, packs.available()["base"])
        assert first.added == 0
        assert first.kept > 0
        mine = packs.Pack(
            "mine",
            1,
            "mine",
            groups=(packs.Group("alimentation", "debit", 100, ("migros", "zorglub")),),
        )
        report = packs.install(conn, mine)
    assert (report.added, report.already) == (1, 1)


def test_export_and_reinstall(finance: FinanceDomain, tmp_path: Path) -> None:
    with begin_immediate(finance.engine()) as conn:
        rules.insert_rule(
            conn,
            id="user-1",
            field="search_text",
            pattern="chez zorglub",
            direction="debit",
            category_id="restaurants",
            priority=50,
        )
        exported = packs.export(conn, "perso", origins=["user"])
    assert [g.keywords for g in exported.groups] == [("chez zorglub",)]
    raw = packs.dump(exported)
    assert packs.parse(raw) == exported
    with pytest.raises(packs.PackError):
        packs.parse("name: X\nversion: 1")
    with pytest.raises(packs.PackError):
        packs.parse("name: x\nversion: 1\nrules:\n- {category: a, keywords: oops}")
    with pytest.raises(packs.PackError):
        packs.export(finance.engine().connect(), "Pas Bon")


def test_cli(finance: FinanceDomain, tmp_path: Path) -> None:
    import json

    app = finance.cli()
    assert app is not None
    runner = CliRunner()
    listed = runner.invoke(app, ["rules", "packs", "list"]).stdout
    assert f"installé v{packs.available()['ch'].version}" in listed
    out = runner.invoke(app, ["rules", "packs", "install", "ch", "--dry-run"])
    assert out.exit_code == 0, out.stdout
    assert json.loads(out.stdout)["packs"][0]["added"] == 0
    assert runner.invoke(app, ["rules", "packs", "install", "xx"]).exit_code == 2
    path = tmp_path / "perso.yaml"
    assert runner.invoke(app, ["rules", "export", str(path), "--origin", "pack-ch"]).exit_code == 0
    assert "migros" in path.read_text()
    renamed = path.read_text().replace("name: perso", "name: copie")
    path.write_text(renamed)
    done = runner.invoke(app, ["rules", "packs", "install", str(path)])
    assert done.exit_code == 0, done.stdout
    assert json.loads(done.stdout)["packs"][0]["already"] > 0
    bad = tmp_path / "bad.yaml"
    bad.write_text("[")
    assert runner.invoke(app, ["rules", "packs", "install", str(bad)]).exit_code == 1
