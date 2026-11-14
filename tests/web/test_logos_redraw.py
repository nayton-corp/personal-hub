"""Les logos ne clignotent plus quand l'écran se redessine (chaque relecture des chiffres refait
la vue en entier, ses <img> comprises) : au premier rendu, chaque logo affiché est déjà chargé
et décodé, et aucun n'est redemandé au serveur."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

import pytest

from tests.web.test_app_mobile import (  # noqa: F401 (fixture du module)
    _hub,
    browse,
    instance,
    open_tab,
)

# les <img> des logos de l'écran, relevées dans la même tâche que le rendu (avant toute peinture)
_PROBE = """() => new Promise((done) => {
  const seen = [];
  const view = document.querySelector('#patrimoine');
  const obs = new MutationObserver(() => {
    for (const img of view.querySelectorAll('.ibox.logo img'))
      seen.push({ src: img.src, ready: img.complete && img.naturalWidth > 0 });
  });
  obs.observe(view, { childList: true, subtree: true });
  document.dispatchEvent(new Event('visibilitychange'));  // retour dans l'app : tout se relit
  setTimeout(() => { obs.disconnect(); done(seen); }, 1500);
})"""


@pytest.fixture(scope="module")
def instance_extra() -> Callable[[dict[str, str]], None]:
    """Un compte d'une plateforme connue, pour qu'un logo s'affiche au patrimoine."""

    def add(env: dict[str, str]) -> None:
        _hub(env, "finance", "accounts", "add", "Revolut", "--institution", "Revolut",
             "--external-ref", "test:revolut")  # fmt: skip

    return add


@pytest.fixture(scope="module")
def page(instance: tuple[str, str]) -> Iterator[Any]:  # noqa: F811
    with browse(*instance) as pg:
        yield pg


def test_logos_are_ready_at_each_redraw_and_never_refetched(page: Any) -> None:
    open_tab(page, "patrimoine")
    # le compte ajouté est vide : sans ce réglage, la liste le masquerait (ligne à zéro)
    page.evaluate("localStorage.setItem('hub.wealth', JSON.stringify({ zero: false }))")
    page.reload()
    open_tab(page, "patrimoine")
    page.wait_for_selector("#patrimoine .ibox.logo img")
    page.wait_for_load_state("networkidle")
    fetched: list[str] = []
    page.on("request", lambda r: fetched.append(r.url) if "/logos/" in r.url else None)
    seen = page.evaluate(_PROBE)
    assert seen, "aucun logo redessiné"
    assert all(s["ready"] for s in seen), [s["src"] for s in seen if not s["ready"]]
    assert fetched == []
    assert page.evaluate("document.querySelector('.ibox.logo img').decoding") != "async"
    assert page.problems == []
