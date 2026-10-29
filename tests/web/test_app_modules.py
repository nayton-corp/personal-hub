"""L'app modulaire (chantier S5) : le domaine factice ajoute un onglet, un bloc d'accueil et une
rubrique à la coquille sans toucher à `shell.js` ni à `index.html` ; ses modules sont copiés à
côté de ceux de l'app, comme le ferait le paquet d'un domaine."""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from hub.core.context import HubContext
from hub.core.registry import Registry
from hub.domains.finance.domain import FinanceDomain
from hub.platform.settings import Paths, Secrets, Server, Settings
from tests.support.demo_domain import DemoDomain
from tests.web.test_app_mobile import ROOT, _free_port, _screen_ok, bootstrap, browse, serve

HERE = Path(__file__).parent


@pytest.fixture(scope="module")
def page(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Any]:
    import pyrage

    home = tmp_path_factory.mktemp("modules")
    web = home / "web"
    shutil.copytree(ROOT / "hub" / "web", web)
    for f in (HERE / "modules").glob("*.js"):
        shutil.copy(f, web / f.name)
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
    assert tabs == ["accueil", "patrimoine", "budget", "journal", "demo"]
    assert page.locator('#tabs button[data-v="demo"]').get_attribute("aria-label") == (
        "Démo, 2 à voir"
    )
    page.click('#tabs button[data-v="demo"]')
    page.wait_for_selector('#tabs button[data-v="demo"][aria-current="page"]')
    _screen_ok(page, "demo")
    assert "0 élément(s) dans le domaine factice des tests, monté 1 fois" in page.inner_text(
        "#demo"
    )


def test_the_demo_adds_a_home_block_and_a_rubric(page: Any) -> None:
    page.click('#tabs button[data-v="accueil"]')
    page.wait_for_load_state("networkidle")
    assert "Démo à l'accueil" in page.inner_text('#accueil [data-home="demo"]')
    page.locator('#accueil [data-a="settings"]').click()
    row = page.locator('#rubrics [data-a="rubric"][data-v="demo-prefs"]')
    assert "prête" in row.inner_text()
    groups = page.locator("#rubrics .grp-title").all_text_contents()
    assert groups == ["Données", "Préférences", "Compte"]
    row.click()
    page.wait_for_selector('#sources [data-rubric="demo-prefs"]:not(.off-rubric)')
    assert "Une rubrique venue du manifeste" in page.inner_text("#sources")
    assert page.problems == []
