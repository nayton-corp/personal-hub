"""Contrat de domaine v2 (chantier S2) : le domaine factice remplit tout le manifeste et apparaît
dans l'app, la boîte d'entrée, les constats, l'assistant et `hub verify` ; un domaine que
`HUB_DOMAINS` éteint n'a ni base, ni route, ni onglet."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from hub.api.app import create_app
from hub.core import connectors, maintenance
from hub.core.context import HubContext
from hub.core.manifest import AppModule, Importer, Manifest, SettingsSection, Tab, unguarded
from hub.core.registry import Registry, contributions
from hub.domains.finance.domain import FinanceDomain
from hub.domains.finance.manifest import MANIFEST as FINANCE
from hub.platform.settings import Settings
from tests.conftest import bearer
from tests.finance.test_finance_api import app_session
from tests.support.demo_domain import MANIFEST as DEMO
from tests.support.demo_domain import DemoDomain

WEB = Path(__file__).resolve().parents[1] / "hub" / "web"


def test_the_app_mounts_what_the_demo_declares(hub: HubContext, client: TestClient) -> None:
    app_session(hub, client)
    (demo,) = client.get("/api/domains").json()["items"]
    assert demo["name"] == "demo"
    assert demo["description"] == DEMO.description
    assert [t["id"] for t in demo["app"]["tabs"]] == ["demo"]
    assert demo["app"]["home_cards"] == [
        {"id": "compte", "label": "Éléments", "endpoint": "/summary"}
    ]
    assert demo["app"]["settings"][0]["group"] == "Préférences"
    assert demo["app"]["cards"] == "demo.js"
    assert (demo["app"]["home"], demo["app"]["module"]) == ("demo-home.js", "demo.js")
    assert demo["importers"] == [
        {"name": "notes", "label": "Notes de démo", "suffixes": [".demo", ".txt"]}
    ]
    # la carte d'accueil pointe une route réelle du domaine
    assert client.get("/api/demo" + demo["app"]["home_cards"][0]["endpoint"]).json() == {"count": 0}


def test_a_token_sees_only_the_domains_it_opens(make_token, client: TestClient) -> None:  # type: ignore[no-untyped-def]
    r = client.get("/api/domains", headers=bearer(make_token("demo:read")))
    assert [d["name"] for d in r.json()["items"]] == ["demo"]
    assert (
        client.get("/api/domains", headers=bearer(make_token("demo:aggregates"))).status_code == 403
    )


def test_the_assistant_gets_the_domain_instructions(make_token, client: TestClient) -> None:  # type: ignore[no-untyped-def]
    r = client.get("/api/tools", headers=bearer(make_token("demo:read")))
    (cap,) = r.json()["domains"]
    assert cap["description"] == DEMO.description
    assert cap["instructions"] == DEMO.assistant


def test_the_inbox_hands_each_file_to_the_domain_that_claims_it(settings: Settings) -> None:
    registry = Registry([DemoDomain(settings.paths.data), FinanceDomain(settings)])
    assert registry.claimant("idee.demo", b"") == "demo"
    assert registry.claimant("note.txt", b"DEMO 1") == "demo"
    assert registry.claimant("note.txt", b"autre chose") is None  # personne : il attend
    assert registry.claimant("releve.xml", b"<?xml") == "finance"
    assert registry.claimant("RAPPORT.PDF", b"%PDF") == "finance"
    assert registry.claimant("photo.heic", b"") is None
    assert registry.claimant("sans-extension", b"") is None


def test_observations_come_from_each_domain(hub: HubContext, demo: DemoDomain) -> None:
    (seen,) = demo.observations(10)
    assert (seen.kind, seen.severity, seen.title) == ("empty", "info", "Aucun élément")
    assert demo.observations(0) == []


def test_finance_turns_its_alerts_into_observations(settings: Settings) -> None:
    finance = FinanceDomain(settings)
    finance.migrate()
    with finance.engine().begin() as conn:
        conn.execute(
            text(
                "INSERT INTO alerts (key, kind, title, detail_json, on_date, created_at) VALUES "
                "('k1', 'budget_over', 'Alimentation', '{}', :d, 'x')"
            ),
            {"d": finance.today().isoformat()},
        )
    (seen,) = finance.observations(5)
    assert (seen.kind, seen.severity, seen.title) == ("budget_over", "alert", "Alimentation")
    finance.engine().dispose()


def test_verify_checks_the_protected_tables(hub: HubContext, demo: DemoDomain) -> None:
    assert maintenance.verify(hub).checks["demo.protected"] == "ok"
    with demo.engine().begin() as conn:
        conn.execute(text("DROP TRIGGER events_no_delete"))
    report = maintenance.verify(hub)
    assert not report.ok
    assert report.checks["demo.protected"] == "sans trigger : events"


def test_the_registry_refuses_a_broken_manifest(settings: Settings, tmp_path: Path) -> None:
    broken = Manifest(
        description=" ",
        app=AppModule(
            tabs=(Tab("a", "A", "x", "../app.js"), Tab("a", "B", "x", "b.js")),
        ),
        importers=(Importer("Mauvais", "x", frozenset({"pdf"})),),
    )
    demo = DemoDomain(tmp_path)
    demo.manifest = lambda: broken  # type: ignore[method-assign]
    with pytest.raises(ValueError, match="manifeste de demo") as exc:
        Registry([demo])
    for problem in ("description vide", "en double : a", "'../app.js'", "'Mauvais'", "'pdf'"):
        assert problem in str(exc.value)


def test_hub_domains_chooses_the_mounted_domains(settings: Settings) -> None:
    def only(value: str) -> Settings:
        return settings.model_copy(update={"domains": value})

    assert Registry.discover(settings).names() == ["agenda", "documents", "finance"]
    assert Registry.discover(only("finance")).names() == ["finance"]
    assert Registry.discover(only("finance, agenda")).names() == ["agenda", "finance"]
    assert Registry.discover(only("")).names() == []
    with pytest.raises(ValueError, match="non installé : maison"):
        Registry.discover(only("finance, maison"))


def test_a_switched_off_domain_has_no_base_no_route_no_tab(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    off = settings.model_copy(update={"domains": ""})
    ctx = HubContext.build(off)
    ctx.migrate_all()
    assert not off.db_path("finance").exists()
    with TestClient(create_app(ctx), base_url="https://hub.example.ts.net") as client:
        app_session(ctx, client)
        assert client.get("/api/domains").json() == {"items": []}
        assert client.get("/api/finance/kpis").status_code == 404
        assert client.get("/api/health").json()["domains"] == {}
    ctx.dispose()
    monkeypatch.setenv("HUB_DOMAINS", "")
    assert contributions("hub.connectors") == []  # ni ses connecteurs
    monkeypatch.setenv("HUB_DOMAINS", "*")
    assert contributions("hub.connectors") != []


def test_the_finance_manifest_matches_the_code(settings: Settings) -> None:
    assert FINANCE.problems() == []
    assert FINANCE.connectors == connectors.names()
    modules = {t.module for t in FINANCE.app.tabs} | {s.module for s in FINANCE.app.settings}
    for module in {*modules, FINANCE.app.cards, FINANCE.app.home, FINANCE.app.module}:
        assert (WEB / str(module)).is_file(), module
    finance = FinanceDomain(settings)
    finance.migrate()
    with finance.engine().connect() as conn:
        assert unguarded(conn, FINANCE.protected_tables) == []
        guarded = conn.execute(
            text(
                "SELECT DISTINCT tbl_name FROM sqlite_master WHERE type = 'trigger' "
                "AND sql LIKE '%append_only%'"
            )
        ).scalars()
        assert set(guarded) == FINANCE.protected_tables  # la liste suit les migrations
    finance.engine().dispose()


def test_every_manifest_field_is_filled_by_the_demo() -> None:
    for f in dataclasses.fields(Manifest):
        if f.name == "connectors":
            continue  # catalogue du point d'entrée hub.connectors : seule la finance en a
        assert getattr(DEMO, f.name) not in ("", (), frozenset(), None), f.name
    for f in dataclasses.fields(AppModule):
        assert getattr(DEMO.app, f.name) not in ((), None), f.name


def test_a_domain_cannot_take_a_screen_of_the_shell_or_of_another(
    settings: Settings, tmp_path: Path
) -> None:
    def demo_with(**changes: object) -> DemoDomain:
        demo = DemoDomain(tmp_path)
        taken = dataclasses.replace(DEMO, app=dataclasses.replace(DEMO.app, **changes))
        demo.manifest = lambda: taken  # type: ignore[method-assign]
        return demo

    with pytest.raises(ValueError, match="écran déjà pris : budget"):
        Registry([FinanceDomain(settings), demo_with(tabs=(Tab("budget", "B", "x", "b.js"),))])
    with pytest.raises(ValueError, match="écran déjà pris : sources"):
        Registry([demo_with(tabs=(Tab("sources", "S", "x", "s.js"),))])
    shell = (SettingsSection("health", "État", "x", "Compte", "d.js"),)
    with pytest.raises(ValueError, match="écran déjà pris : health"):
        Registry([demo_with(settings=shell)])
