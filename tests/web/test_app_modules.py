"""L'app modulaire (chantier S5) : le domaine factice ajoute un onglet, un bloc d'accueil et une
rubrique à la coquille sans toucher à `shell.js` ni à `index.html` ; ses modules sont servis
depuis le dossier que déclare son manifeste, sous /d/demo/, comme ceux d'un vrai domaine."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from hub.core.context import HubContext
from hub.core.registry import Registry
from hub.domains.finance.domain import FinanceDomain
from hub.platform.settings import Paths, Secrets, Server, Settings
from tests.support.demo_domain import DemoDomain
from tests.web.test_app_mobile import ROOT, _free_port, _screen_ok, bootstrap, browse, serve


@pytest.fixture(scope="module")
def page(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Any]:
    import pyrage

    home = tmp_path_factory.mktemp("modules")
    web = ROOT / "hub" / "web"  # les modules du domaine factice sont servis depuis son dossier
    key = home / "age.key"
    key.write_text(f"{pyrage.x25519.Identity.generate()}\n")
    port = _free_port()
    origin = f"http://localhost:{port}"
    settings = Settings(
        paths=Paths(**{k: home / k for k in ("data", "inbox", "archive", "backup")}),
        server=Server(public_origin=origin, web_root=web),
        secrets=Secrets(age_key_file=key),
    )
    hub = HubContext.build(
        settings, Registry([FinanceDomain(settings), DemoDomain(settings.paths.data)])
    )
    hub.migrate_all()
    with serve(hub, port), browse(origin, bootstrap(hub)) as pg:
        yield pg
    hub.dispose()


def test_the_demo_tab_comes_from_its_manifest(page: Any) -> None:
    page.wait_for_selector('#tabs button[data-v="demo"]')
    tabs = page.locator("#tabs button").evaluate_all("bs => bs.map(b => b.dataset.v)")
    assert tabs == ["accueil", "assistant", "finance", "demo"]  # l'orbe, puis un espace par domaine
    assert page.locator('#tabs button[data-v="demo"]').get_attribute("aria-label") == (
        "Démo, 2 à voir"
    )
    page.click('#tabs button[data-v="demo"]')
    page.wait_for_selector('#tabs button[data-v="demo"][aria-current="page"]')
    _screen_ok(page, "demo")
    assert "0 élément(s) dans le domaine factice des tests, monté 1 fois" in page.inner_text(
        "#demo"
    )


def test_a_space_with_several_tabs_puts_them_at_the_top(page: Any) -> None:
    """La finance est une seule entrée de la barre du bas ; ses onglets sont la barre du haut,
    et l'espace rouvre le dernier onglet vu."""
    page.click('#tabs button[data-v="finance"]')
    page.wait_for_selector('#tabs button[data-v="finance"][aria-current="page"]')
    subs = page.locator("#patrimoine .subtabs button").all_text_contents()
    assert subs == ["Patrimoine", "Budget", "Journal"]
    page.click('#patrimoine .subtabs button[data-v="journal"]')
    page.wait_for_selector('#journal .subtabs button[data-v="journal"][aria-current="page"]')
    assert page.locator("#journal .topbar-title").bounding_box()["width"] <= 1  # lecteurs d'écran
    page.click('#tabs button[data-v="accueil"]')
    page.click('#tabs button[data-v="finance"]')
    page.wait_for_selector("#journal:not([hidden])")
    assert page.problems == []


def test_the_demo_adds_a_home_block_and_a_rubric(page: Any) -> None:
    page.click('#tabs button[data-v="accueil"]')
    page.wait_for_load_state("networkidle")
    assert "Démo à l'accueil" in page.inner_text('#accueil [data-home="demo"]')
    page.locator('#accueil [data-a="settings"]').click()
    row = page.locator('#rubrics [data-a="rubric"][data-v="demo-prefs"]')
    assert "prête" in row.inner_text()
    groups = page.locator("#rubrics .grp-title").all_text_contents()
    assert groups == ["Hub", "Finance", "Demo"]  # le hub, puis une section par domaine
    row.click()
    page.wait_for_selector('#sources [data-rubric="demo-prefs"]:not(.off-rubric)')
    assert "Une rubrique venue du manifeste" in page.inner_text("#sources")
    assert page.problems == []


def test_the_home_and_its_approvals_belong_to_the_shell(page: Any) -> None:
    """L'accueil et « À valider » sont au cœur : la carte d'un autre domaine que la finance s'y
    valide ; « À faire » passe avant les blocs de tous les domaines, finance comprise, et chaque
    ligne d'un domaine porte son nom."""
    page.click('#tabs button[data-v="accueil"]')
    page.evaluate(
        """fetch('/api/proposals', {method: 'POST', headers: {'Content-Type': 'application/json'},
           body: JSON.stringify({domain: 'demo', kind: 'add_item', params: {name: 'lampe'}})})"""
    )
    page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")  # tout se relit
    row = page.locator('#accueil [data-lists] [data-a="props"]')
    row.wait_for()
    # la carte « À valider » ouvre l'accueil : la proposition cochée et le Face ID du lot
    head = page.locator("#accueil [data-lists] .card").first
    assert "À valider" in head.inner_text()
    assert "ajouter lampe" in head.inner_text()
    assert "Valider 1 avec Face ID" in head.inner_text()
    order = page.locator("#homeBody > div").evaluate_all(
        "ds => ds.map(d => d.dataset.home ?? (d.dataset.lists === undefined ? '' : 'listes'))"
    )
    assert order == ["listes", "finance", "demo", ""]
    row.click()
    sheet = page.locator("#sheet")
    sheet.wait_for()
    assert "ajouter lampe" in sheet.inner_text()
    assert "Rien ne change sans ton Face ID" in sheet.inner_text()
    sheet.locator('[data-a="prop-reject"]').click()
    page.wait_for_selector('#accueil [data-lists] [data-a="props"]', state="detached")
    assert page.problems == []
