"""Navigateur des bots (Playwright, Chromium) : sélecteurs nommés, liste blanche des clics,
captures de diagnostic seulement sur demande.

Tous les sélecteurs d'un site vivent dans son `selectors.toml`, nommés par étape
(`export.button`) : un changement de site se corrige dans ce seul fichier. Un clic sur un nom
absent de `[clicks] allowed` fait échouer le run. Les éléments sont cherchés dans toutes les
frames, comme le demandent les écrans de la BCF.
"""

from __future__ import annotations

import re
import time
import tomllib
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from hub.collectors.base import Failure
from hub.core.clock import utcnow

if TYPE_CHECKING:
    from playwright.sync_api import BrowserContext, Download, ElementHandle, Frame, Page

POLL_MS = 400


class Selectors:
    def __init__(self, data: dict[str, Any]) -> None:
        self.data = data
        self.allowed = frozenset(data.get("clicks", {}).get("allowed", []))

    @classmethod
    def load(cls, path: Path, site: dict[str, str] | None = None) -> Selectors:
        """`site` remplace des adresses de la section `[site]` (faux site des tests)."""
        data = tomllib.loads(path.read_text())
        data.setdefault("site", {}).update(site or {})
        return cls(data)

    def get(self, name: str) -> str:
        section, _, key = name.partition(".")
        value = self.data.get(section, {}).get(key)
        if not isinstance(value, str):
            raise KeyError(f"sélecteur absent : {name}")
        return value

    def site(self, key: str) -> str:
        return self.get(f"site.{key}")

    def items(self, name: str) -> list[str]:
        section, _, key = name.partition(".")
        value = self.data.get(section, {}).get(key, [])
        return [str(v) for v in value]

    def names(self) -> list[str]:
        """Tous les sélecteurs d'éléments (hors `site` et `clicks`), pour le mode contrôle."""
        out = []
        for section, values in self.data.items():
            if section in {"site", "clicks"} or not isinstance(values, dict):
                continue
            out += [f"{section}.{k}" for k, v in values.items() if isinstance(v, str)]
        return out


def _deadline(timeout_ms: int) -> int:
    return time.monotonic_ns() + timeout_ms * 1_000_000


class Browser:
    """Une session : profil persistant, fuseau de Zurich, téléchargements acceptés."""

    def __init__(
        self,
        context: BrowserContext,
        selectors: Selectors,
        diag: Path | None = None,
    ) -> None:
        self.context = context
        self.sel = selectors
        self.diag = diag
        self.page: Page = context.pages[0] if context.pages else context.new_page()
        self.downloads: list[Download] = []
        self.page.on("download", self._got)
        context.on("page", lambda p: p.on("download", self._got))

    def _got(self, download: Download) -> None:
        self.downloads.append(download)

    # --- navigation et recherche ---------------------------------------------------------------

    def goto(self, url: str, step: str) -> None:
        from playwright.sync_api import Error as PwError

        try:
            try:
                self.page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            except PwError:
                # navigation interrompue par une redirection de l'app : un second essai suffit
                self.settle(5_000)
                self.page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        except PwError as exc:
            # nom du réseau, délai : le site ne répond pas ; jamais le texte de la page
            raise Failure("site_unavailable", f"{step}:{type(exc).__name__.lower()}") from None

    def settle(self, timeout_ms: int = 15_000) -> None:
        """Attend la fin d'une navigation lancée par un envoi de formulaire."""
        from playwright.sync_api import Error as PwError

        try:
            self.page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
            self.page.wait_for_load_state("networkidle", timeout=timeout_ms)
        except PwError:
            pass  # une page qui bavarde sans fin ne bloque pas : la suite vérifie l'état

    def frames(self) -> list[Frame]:
        return list(self.page.frames)

    def find(self, name: str, timeout_ms: int = 10_000) -> ElementHandle | None:
        css = self.sel.get(name)
        end = _deadline(timeout_ms)
        while True:
            for frame in self.frames():
                try:
                    for el in frame.query_selector_all(css):
                        if el.is_visible():
                            return el
                except Exception:  # noqa: S112 - frame détachée pendant la navigation
                    continue
            if time.monotonic_ns() >= end:
                return None
            self.page.wait_for_timeout(POLL_MS)

    def exists(self, name: str, timeout_ms: int = 5_000) -> bool:
        """Présent dans le DOM, visible ou non (cases à cocher masquées, etc.)."""
        css = self.sel.get(name)
        end = _deadline(timeout_ms)
        while True:
            for frame in self.frames():
                try:
                    if frame.query_selector(css) is not None:
                        return True
                except Exception:  # noqa: S112
                    continue
            if time.monotonic_ns() >= end:
                return False
            self.page.wait_for_timeout(POLL_MS)

    def frame_of(self, name: str, timeout_ms: int = 10_000) -> Frame | None:
        css = self.sel.get(name)
        end = _deadline(timeout_ms)
        while True:
            for frame in self.frames():
                try:
                    if frame.query_selector(css) is not None:
                        return frame
                except Exception:  # noqa: S112
                    continue
            if time.monotonic_ns() >= end:
                return None
            self.page.wait_for_timeout(POLL_MS)

    def require(self, name: str, timeout_ms: int = 10_000) -> ElementHandle:
        el = self.find(name, timeout_ms)
        if el is None:
            self.snap(name)
            raise Failure("selector_missing", name)
        return el

    def click(self, name: str, timeout_ms: int = 10_000) -> None:
        if name not in self.sel.allowed:
            raise Failure("unknown", f"whitelist:{name}")
        self.require(name, timeout_ms).click()

    def text_matches(self, pattern: str) -> bool:
        """Repère un état à l'écran (connecté, mot de passe refusé). Le texte n'est jamais gardé."""
        rx = re.compile(pattern)
        for frame in self.frames():
            try:
                if rx.search(frame.inner_text("body", timeout=2_000)):
                    return True
            except Exception:  # noqa: S112
                continue
        return False

    def wait_for(self, checks: dict[str, Callable[[], bool]], timeout_ms: int) -> str | None:
        """Premier état atteint parmi `checks`, ou None à l'échéance."""
        end = _deadline(timeout_ms)
        while True:
            for state, check in checks.items():
                if check():
                    return state
            if time.monotonic_ns() >= end:
                return None
            self.page.wait_for_timeout(POLL_MS * 2)

    # --- téléchargement --------------------------------------------------------------------

    def download_after(
        self, click: str, timeout_ms: int, give_up: Callable[[], bool] | None = None
    ) -> bytes | None:
        """Clique `click` et attend un téléchargement, dans la page ou dans un nouvel onglet ;
        `give_up` arrête l'attente plus tôt (« rien à exporter » affiché)."""
        self.downloads.clear()
        self.click(click)
        end = _deadline(timeout_ms)
        while not self.downloads:
            if time.monotonic_ns() >= end or (give_up is not None and give_up()):
                return None
            self.page.wait_for_timeout(POLL_MS)
        d = self.downloads.pop(0)
        path = d.path()
        data = Path(path).read_bytes()
        d.delete()
        return data

    # --- diagnostic ------------------------------------------------------------------------

    def snap(self, step: str) -> None:
        if self.diag is None:
            return
        self.diag.mkdir(parents=True, exist_ok=True)
        name = f"{utcnow().strftime('%Y%m%dT%H%M%S')}-{re.sub(r'[^a-z0-9._-]', '-', step)}.png"
        with suppress(Exception):  # un diagnostic raté ne change pas le résultat
            self.page.screenshot(path=str(self.diag / name), full_page=True)


@contextmanager
def open_browser(
    profile: Path, selectors: Selectors, *, headless: bool = True, diag: Path | None = None
) -> Iterator[Browser]:
    from playwright.sync_api import sync_playwright

    profile.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(profile),
            headless=headless,
            viewport={"width": 1366, "height": 900},
            locale="fr-CH",
            timezone_id="Europe/Zurich",
            accept_downloads=True,
            args=["--disable-dev-shm-usage"],
        )
        try:
            yield Browser(context, selectors, diag)
        finally:
            context.close()


def purge_diag(diag: Path, keep_days: int) -> int:
    if not diag.is_dir():
        return 0
    limit = (utcnow() - timedelta(days=keep_days)).timestamp()
    count = 0
    for p in diag.rglob("*"):
        if p.is_file() and p.stat().st_mtime < limit:
            p.unlink()
            count += 1
    return count
