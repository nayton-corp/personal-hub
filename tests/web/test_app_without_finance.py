"""La coquille ne dépend d'aucun domaine : montée avec le seul domaine factice, sans la
finance, l'app démarre, avec son accueil et ses réglages communs."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from hub.core.context import HubContext
from hub.core.registry import Registry
from hub.platform.settings import Paths, Secrets, Server, Settings
from tests.support.demo_domain import DemoDomain
from tests.web.test_app_mobile import ROOT, _free_port, bootstrap, browse, serve


@pytest.fixture(scope="module")
def without_finance(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Any]:
    import pyrage

    home = tmp_path_factory.mktemp("sans-finance")
    key = home / "age.key"
    key.write_text(f"{pyrage.x25519.Identity.generate()}\n")
    port = _free_port()
    origin = f"http://localhost:{port}"
    settings = Settings(
        paths=Paths(**{k: home / k for k in ("data", "inbox", "archive", "backup")}),
        server=Server(public_origin=origin, web_root=ROOT / "hub" / "web"),
        secrets=Secrets(age_key_file=key),
    )
    hub = HubContext.build(settings, Registry([DemoDomain(settings.paths.data)]))
    hub.migrate_all()
    with serve(hub, port), browse(origin, bootstrap(hub)) as pg:
        yield pg
    hub.dispose()


def test_the_app_starts_without_finance(without_finance: Any) -> None:
    """La coquille ne dépend d'aucun domaine : sans la finance, l'accueil, « À faire » et les
    réglages communs s'affichent, sans erreur ni appel à une route absente."""
    page = without_finance
    page.wait_for_selector('#tabs button[data-v="demo"]')
    tabs = page.locator("#tabs button").evaluate_all("bs => bs.map(b => b.dataset.v)")
    assert tabs == ["accueil", "demo"]
    page.wait_for_selector("#accueil [data-lists] #t-todo")
    assert "Démo à l'accueil" in page.inner_text("#accueil")
    page.locator('#accueil [data-a="settings"]').click()
    page.wait_for_selector('#rubrics [data-a="rubric"][data-v="demo-prefs"]')
    page.wait_for_load_state("networkidle")
    assert page.locator("#patrimoine, #budget, #journal").count() == 0
    assert page.problems == []
