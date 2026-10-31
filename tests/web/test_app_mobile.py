"""L'app dans un vrai navigateur, à 375 px, sur un an de données fictives (chantier S13).

Le hub tourne comme en développement (`make dev`) : l'API sert l'app. Chromium crée la première
passkey avec un authentificateur virtuel, puis le test ouvre chaque écran. Un écran passe s'il
s'affiche sans erreur JavaScript ni réponse 5xx, sans défilement horizontal, et avec du contenu.
Les captures vont dans `HUB_SCREENSHOTS` quand la variable est posée (artefact de la CI).
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import os
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from hub.core import sessions
from hub.core.context import HubContext
from hub.core.registry import Registry
from hub.domains.agenda.domain import AgendaDomain
from hub.platform.settings import Paths, Secrets, Server, Settings
from tests.agenda.test_agenda import FakeBridge
from tests.documents.test_documents import library

playwright = pytest.importorskip("playwright.sync_api")

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("demo_data", ROOT / "scripts" / "demo_data.py")
assert _spec
assert _spec.loader
demo_data = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(demo_data)

WIDTH, HEIGHT = 375, 812
TABS = ["accueil", "patrimoine", "budget", "journal"]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _hub(env: dict[str, str], *args: str) -> None:
    cmd = [sys.executable, "-m", "hub.cli", *args]
    subprocess.run(cmd, env=env, check=True, capture_output=True)  # noqa: S603 - arguments du test


@contextmanager
def serve(hub: HubContext, port: int) -> Iterator[None]:
    """L'API de `hub`, servant l'app, dans un fil, le temps du bloc."""
    import uvicorn

    from hub.api.app import create_app

    server = uvicorn.Server(
        uvicorn.Config(
            create_app(hub), host="127.0.0.1", port=port, log_config=None, access_log=False
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 15
    while not server.started:
        assert time.monotonic() < deadline, "l'API ne démarre pas"
        time.sleep(0.05)
    yield
    server.should_exit = True
    thread.join(timeout=10)


def bootstrap(hub: HubContext) -> str:
    with hub.core.engine.begin() as conn:
        return sessions.create_bootstrap_code(conn, 10, "system:test")


@pytest.fixture(scope="module")
def instance(tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[str, str]]:
    """Une instance complète : bases migrées, deux comptes, un an de relevés, API servant l'app."""
    import pyrage

    home = tmp_path_factory.mktemp("instance")
    key = home / "age.key"
    key.write_text(f"{pyrage.x25519.Identity.generate()}\n")
    key.chmod(0o400)
    port = _free_port()
    origin = f"http://localhost:{port}"
    paths = {k: home / k for k in ("data", "inbox", "archive", "backup")}
    env = {
        **os.environ,
        "HUB_SETTINGS": str(home / "absent.toml"),
        "HUB_SECRETS__AGE_KEY_FILE": str(key),
        "HUB_SERVER__PUBLIC_ORIGIN": origin,
        **{f"HUB_PATHS__{k.upper()}": str(p) for k, p in paths.items()},
    }
    _hub(env, "db", "upgrade")
    demo = home / "demo"
    demo_data.write(demo, dt.date.today())  # noqa: DTZ011 (le mois en cours doit avoir des données)
    for line in (demo / "accounts.tsv").read_text().splitlines():
        iban, name, options = line.split("\t")
        _hub(env, "finance", "accounts", "add", name, "--iban", iban, *options.split())
    _hub(env, "finance", "import-history", str(demo))
    _hub(env, "documents", "import-library", str(library(home / "Bibliothèque")))

    settings = Settings(
        paths=Paths(**paths),
        server=Server(public_origin=origin, web_root=ROOT / "hub" / "web"),
        secrets=Secrets(age_key_file=key),
    )
    # l'agenda lit un pont factice : son bloc d'accueil a des lignes, comme sur le Mac
    found = Registry.discover(settings)
    agenda = AgendaDomain(settings, FakeBridge())
    hub = HubContext.build(settings, Registry(agenda if d.name == "agenda" else d for d in found))
    with serve(hub, port):
        yield origin, bootstrap(hub)
    hub.dispose()


@contextmanager
def browse(origin: str, code: str) -> Iterator[Any]:
    """Chromium à 375 px, la première passkey créée : la page est dans la coquille de l'app."""
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(
            viewport={"width": WIDTH, "height": HEIGHT},
            device_scale_factor=2,
            is_mobile=True,
            has_touch=True,
            locale="fr-CH",
            timezone_id="Europe/Zurich",
            service_workers="block",
        )
        pg = context.new_page()
        cdp = context.new_cdp_session(pg)
        cdp.send("WebAuthn.enable")
        cdp.send(
            "WebAuthn.addVirtualAuthenticator",
            {
                "options": {
                    "protocol": "ctap2",
                    "transport": "internal",
                    "hasResidentKey": True,
                    "hasUserVerification": True,
                    "isUserVerified": True,
                }
            },
        )
        problems: list[str] = []
        pg.on("pageerror", lambda e: problems.append(f"JS : {e}"))
        pg.on(
            "console",
            lambda m: problems.append(f"console : {m.text}") if m.type == "error" else None,
        )
        pg.on(
            "response",
            lambda r: problems.append(f"{r.status} {r.url}") if r.status >= 500 else None,
        )
        pg.problems = problems  # type: ignore[attr-defined]
        pg.goto(origin)
        pg.fill("#code", code)
        pg.fill("#device", "Navigateur de test")
        pg.click("#form-bootstrap button[type=submit]")
        pg.wait_for_selector("#shell:not([hidden])", timeout=15_000)
        yield pg
        browser.close()


@pytest.fixture(scope="module")
def page(instance: tuple[str, str]) -> Iterator[Any]:
    with browse(*instance) as pg:
        yield pg


def _screen_ok(pg: Any, name: str, shot: str | None = None) -> None:
    pg.wait_for_load_state("networkidle")
    pg.wait_for_timeout(300)  # le rendu qui suit la dernière réponse
    view = pg.locator(f"#{name}")
    assert view.is_visible(), f"{name} : écran caché"
    text = view.inner_text()
    assert len(text.strip()) > 40, f"{name} : écran presque vide"
    assert "Erreur" not in text, f"{name} : {text[:200]}"
    overflow = pg.evaluate("document.documentElement.scrollWidth - window.innerWidth")
    assert overflow <= 0, f"{name} : {overflow} px de défilement horizontal à {WIDTH} px"
    shots = os.environ.get("HUB_SCREENSHOTS")
    if shots:
        Path(shots).mkdir(parents=True, exist_ok=True)
        pg.screenshot(path=str(Path(shots) / f"{shot or name}.png"), full_page=True)
    assert pg.problems == [], f"{name} : {pg.problems}"


def open_tab(pg: Any, tab: str) -> None:
    """L'accueil est dans la barre du bas ; les écrans de la finance, sous son espace."""
    if tab == "accueil":
        pg.click('#tabs button[data-v="accueil"]')
    else:
        pg.click('#tabs button[data-v="finance"]')
        pg.wait_for_selector('#tabs button[data-v="finance"][aria-current="page"]')
        here = pg.evaluate("document.querySelector('.view:not([hidden])').id")
        pg.click(f'#{here} .subtabs button[data-v="{tab}"]')
    pg.wait_for_selector(f"#{tab}:not([hidden])")


@pytest.mark.parametrize("tab", TABS)
def test_each_tab_renders_at_375px(page: Any, tab: str) -> None:
    open_tab(page, tab)
    _screen_ok(page, tab)


def test_sources_and_settings_render_at_375px(page: Any) -> None:
    page.click('#tabs button[data-v="accueil"]')
    page.locator('#accueil [data-a="settings"]').click()
    _screen_ok(page, "sources")


def test_home_rows_of_every_domain_use_the_full_width(page: Any) -> None:
    """Une ligne sans pastille (agenda, documents) prend toute la largeur : son titre tombait
    dans la colonne de 38 px de l'icône (« Soi… »)."""
    page.click('#tabs button[data-v="accueil"]')
    for d in ("agenda", "documents"):
        title = page.locator(f'#accueil [data-home="{d}"] .row-title').first
        title.wait_for()
        assert title.evaluate("e => e.getBoundingClientRect().width") > 200, d
    assert "Lave-linge" in page.inner_text('#accueil [data-home="documents"]')
    subs = page.locator("#accueil [data-lists] .row-sub").all_text_contents()
    assert any(x.startswith("Finance · ") for x in subs), subs


def test_the_year_of_demo_data_reaches_the_screens(page: Any) -> None:
    open_tab(page, "journal")
    page.wait_for_load_state("networkidle")
    assert "Employeur Fictif SA" in page.locator("#journal").inner_text()


RUBRICS = [
    "conn",
    "accounts",
    "debts",
    "export",
    "budget",
    "tax",
    "display",
    "profile",
    "security",
    "health",
]


@pytest.mark.parametrize("rubric", RUBRICS)
def test_each_settings_rubric_renders_at_375px(page: Any, rubric: str) -> None:
    page.click('#tabs button[data-v="accueil"]')
    page.locator('#accueil [data-a="settings"]').click()
    page.locator(f'#rubrics [data-a="rubric"][data-v="{rubric}"]').click()
    page.wait_for_selector(f'#sources [data-rubric="{rubric}"]:not(.off-rubric)', state="attached")
    _screen_ok(page, "sources", shot=f"sources-{rubric}")
    page.locator('#sources [data-a="back"]').click()
