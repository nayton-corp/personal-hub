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
from collections.abc import Callable, Iterator
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
TABS = ["accueil", "apercu", "patrimoine", "budget", "journal"]


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
def instance(
    tmp_path_factory: pytest.TempPathFactory, instance_extra: Callable[[dict[str, str]], None]
) -> Iterator[tuple[str, str]]:
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
    instance_extra(env)
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
        pg.wait_for_selector("#tabs-start button")  # onglets dessinés (l'orbe, elle, est fixe)
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


def _where(pg: Any) -> str:
    """L'état de l'écran, pour un échec qui dit où l'on était."""
    return str(
        pg.evaluate(
            "({url: location.href, params: localStorage.getItem('hub.params'),"
            " views: [...document.querySelectorAll('.view:not([hidden])')].map((v) => v.id),"
            " bar: [...document.querySelectorAll('#tabs button')].map((b) => b.dataset.v),"
            " sheet: document.documentElement.classList.contains('sheet-open')})"
        )
    )


def go_home(pg: Any) -> None:
    """L'accueil du hub : dans la barre du bas, ou par le bouton d'espace quand la barre est
    celle d'un espace (depuis les réglages, on en sort d'abord)."""
    pg.wait_for_selector(".view:not([hidden])")
    if pg.evaluate("document.documentElement.classList.contains('sheet-open')"):
        pg.locator("#sheet [data-a='sheet-close']").first.click()
    for _ in range(3):  # d'une rubrique à la liste, puis hors des réglages (parfois l'accueil)
        if not pg.locator("#sources:not([hidden])").count():
            break
        pg.locator('#sources [data-a="back"]').click()
        pg.wait_for_timeout(150)
    if pg.locator("#accueil:not([hidden])").count():
        return
    if pg.locator('#tabs button[data-v="accueil"]').count():
        pg.click('#tabs button[data-v="accueil"]')
    else:
        spaces = pg.locator('.view:not([hidden]) [data-a="spaces"]')
        try:
            spaces.first.click(timeout=10_000)
        except Exception as exc:  # l'échec doit dire où l'on était
            raise AssertionError(f"aucun chemin vers l'accueil : {_where(pg)}") from exc
        pg.click('#sheet [data-a="hub"]')
    pg.wait_for_selector("#accueil:not([hidden])")


def open_settings(pg: Any, space: str | None = None) -> None:
    """Les réglages du hub (depuis l'accueil) ou ceux d'un espace (depuis sa roue)."""
    if space is None:
        go_home(pg)
        pg.locator('#accueil [data-a="settings"]').click()
    else:
        open_tab(pg, "patrimoine")
        pg.locator('#patrimoine [data-a="settings"]').click()
    pg.wait_for_selector("#rubrics:not([hidden])")


def open_tab(pg: Any, tab: str) -> None:
    """L'accueil est dans la barre du hub ; les écrans de la finance, dans la barre de son
    espace, qui remplace celle du hub dès qu'on y entre."""
    if tab == "accueil":
        go_home(pg)
    else:
        if not pg.locator(f'#tabs button[data-a="tab"][data-v="{tab}"]').count():
            go_home(pg)
            pg.click('#tabs button[data-v="finance"]')
        pg.click(f'#tabs button[data-a="tab"][data-v="{tab}"]')
    pg.wait_for_selector(f"#{tab}:not([hidden])")
    if tab == "journal":  # ses écritures arrivent hors du store : « networkidle » peut les devancer
        pg.wait_for_selector("#journal .tx-row")


@pytest.mark.parametrize("tab", TABS)
def test_each_tab_renders_at_375px(page: Any, tab: str) -> None:
    open_tab(page, tab)
    _screen_ok(page, tab)


def test_sources_and_settings_render_at_375px(page: Any) -> None:
    go_home(page)
    page.locator('#accueil [data-a="settings"]').click()
    _screen_ok(page, "sources")


def test_agenda_and_documents_only_surface_what_needs_attention(page: Any) -> None:
    """L'agenda et les documents n'ont plus de bloc à l'accueil : le rappel en retard et
    l'entretien dû remontent dans « À savoir », à pleine largeur, et ouvrent l'assistant."""
    go_home(page)
    page.wait_for_selector("#accueil [data-lists] #t-info")
    for d in ("agenda", "documents"):
        assert page.inner_text(f'#accueil [data-home="{d}"]') == "", d
    info = page.locator("#accueil [data-lists] section:has(#t-info)")
    subs = info.locator(".row-sub").all_text_contents()
    assert any(x.startswith("Agenda · Rappel en retard") for x in subs), subs
    assert any(x.startswith("Documents · Entretien dû") for x in subs), subs
    assert "Payer l'assurance" in info.inner_text()
    assert "Lave-linge" in info.inner_text()
    title = info.locator('.row-title:has-text("Payer l\'assurance")')
    assert title.evaluate("e => e.getBoundingClientRect().width") > 200
    subs = page.locator("#accueil [data-lists] .row-sub").all_text_contents()
    assert any(x.startswith("Finance · ") for x in subs), subs
    info.locator('[data-a="assistant-open"]').first.click()
    page.wait_for_selector("#assistant:not([hidden])")
    assert page.problems == []


def test_the_year_of_demo_data_reaches_the_screens(page: Any) -> None:
    open_tab(page, "journal")
    page.wait_for_load_state("networkidle")
    assert "Employeur Fictif SA" in page.locator("#journal").inner_text()


HUB_RUBRICS = {"display", "profile", "security", "health"}
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
    open_settings(page, None if rubric in HUB_RUBRICS else "finance")
    page.locator(f'#rubrics [data-a="rubric"][data-v="{rubric}"]').click()
    page.wait_for_selector(f'#sources [data-rubric="{rubric}"]:not(.off-rubric)', state="attached")
    _screen_ok(page, "sources", shot=f"sources-{rubric}")
    page.locator('#sources [data-a="back"]').click()


def test_an_account_filters_the_screen_and_back_returns_home(page: Any) -> None:
    """Un compte de la liste filtre l'écran : la pilule porte son nom, sans chemin ni nouvelle
    page ; le retour du navigateur ramène au patrimoine entier. Le plein écran est rangé dans
    Affichage, et on en revient."""
    open_tab(page, "patrimoine")
    page.wait_for_load_state("networkidle")
    page.locator('#patrimoine [data-a="w-open"][data-v^="a:"]').first.click()
    page.wait_for_selector("#filterbar .scope.on")
    assert page.locator("#patCrumbs").is_hidden()
    assert page.locator('#filterbar [data-a="w-home"]').count() == 1
    _screen_ok(page, "patrimoine", shot="patrimoine-compte")
    page.go_back()
    page.wait_for_selector("#filterbar .scope:not(.on)")
    assert page.locator("#patrimoine .toolbar").count() == 0  # plus de barre d'outils sur l'écran
    page.locator('#patrimoine [data-a="w-display"]').click()
    page.locator('#sheet [data-a="w-full"][data-v="1"]').click()
    page.wait_for_selector("#wland:not([hidden]) svg")
    page.locator('#wland [data-a="w-full"][data-v="0"]').click()
    page.wait_for_selector("#wland", state="hidden")
    _screen_ok(page, "patrimoine")


def test_wealth_cards_open_tall_sheets_and_strategies_unfold(page: Any) -> None:
    """Répartition, Rendement et Stratégies tiennent en trois cartes. Les deux premières
    ouvrent leur détail dans un grand panneau ; Stratégies se déplie sur place et mène à
    « Que veux-tu faire ? », la quatrième intention annoncée sans être ouverte."""
    page.reload()
    page.wait_for_selector("#tabs-start button")  # onglets dessinés (l'orbe, elle, est fixe)
    open_tab(page, "patrimoine")
    page.wait_for_selector("#patrimoine .wcards .sumcard")
    assert page.locator("#patrimoine .wcards .sumcard").count() == 3
    page.locator('#patrimoine [data-a="w-card"][data-v="alloc"]').click()
    page.wait_for_selector("#sheet.tall .alloc-row")
    page.locator('#sheet [data-a="sheet-close"]').click()
    page.locator('#patrimoine [data-a="w-card"][data-v="rend"]').click()
    page.wait_for_selector("#sheet.tall #tabSeg")
    page.locator('#sheet [data-a="sheet-close"]').click()
    page.locator('#patrimoine .sumcard[data-a="w-fold"][data-v="strat"]').click()
    page.locator('#sec-strat [data-a="strat-new"]').click()
    page.wait_for_selector('#sheet [data-a="strat-kind"]')
    assert page.locator('#sheet [data-a="strat-kind"]').count() == 3
    assert "Bientôt" in page.locator("#sheet button[disabled]").inner_text()
    page.locator('#sheet [data-a="strat-kind"][data-v="recurring"]').click()
    page.wait_for_selector("#sf-amount")
    assert page.locator('#sheet [data-a="strat-save"]').count() == 1
    page.locator('#sheet [data-a="sheet-close"]').click()
    _screen_ok(page, "patrimoine", shot="patrimoine-strategies")
