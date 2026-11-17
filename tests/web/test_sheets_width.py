"""Les panneaux du bas tiennent dans la largeur d'un petit téléphone.

Chaque panneau qui s'ouvre sans contexte est ouvert à 320 px : son corps et son pied ne défilent
pas de côté et aucun champ ne dépasse le bord droit du panneau. Chromium ne reproduit pas la
largeur qu'iOS impose à un champ date natif : le test vérifie donc que ces champs perdent leur
apparence native, seule façon pour Safari de leur faire suivre la largeur de leur colonne.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from tests.web.test_app_mobile import browse, instance, open_tab  # noqa: F401 - fixture partagée

playwright = pytest.importorskip("playwright.sync_api")

NARROW = 320

# chaque panneau ouvrable sans contexte, mesuré : défilement de côté, champs qui dépassent,
# champs date encore natifs ; les rangées de puces qui défilent d'elles-mêmes sont mises à part
SWEEP = """async () => {
  const ui = await import('/ui.js');
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  const html = document.documentElement, out = {};
  for (const kind of Object.keys(ui.SHEETS)) {
    try { ui.openSheet(kind, null); } catch { continue; }
    await wait(350);
    if (!html.classList.contains('sheet-open')) continue;
    const s = document.getElementById('sheet');
    const body = document.getElementById('sheet-body');
    const foot = document.getElementById('sheet-foot');
    const right = s.getBoundingClientRect().right;
    const over = [...s.querySelectorAll('input, select, textarea, button, .seg, .jf-pair')]
      .filter((e) => e.offsetParent && !e.closest('.hscroll'))
      .filter((e) => e.getBoundingClientRect().right > right + 0.5)
      .map((e) => e.outerHTML.slice(0, 80));
    const native = [...s.querySelectorAll('input[type=date], input[type=month], input[type=time]')]
      .filter((e) => getComputedStyle(e).appearance !== 'none').length;
    out[kind] = {
      scroll: body.scrollWidth - body.clientWidth, foot: foot.scrollWidth - foot.clientWidth,
      over, native, dates: s.querySelectorAll('input[type=date]').length,
    };
    ui.closeSheet();
    await wait(250);
  }
  return out;
}"""


@pytest.fixture(scope="module")
def narrow(instance: tuple[str, str]) -> Iterator[Any]:  # noqa: F811
    with browse(*instance) as pg:
        pg.set_viewport_size({"width": NARROW, "height": 700})
        yield pg


def test_every_sheet_fits_a_phone(narrow: Any) -> None:
    open_tab(narrow, "journal")  # les panneaux sont communs à tous les écrans
    narrow.wait_for_load_state("networkidle")
    seen = narrow.evaluate(SWEEP)
    assert "jfilter" in seen, f"le filtre du journal ne s'ouvre pas : {sorted(seen)}"
    assert sum(m["dates"] for m in seen.values()) >= 2, "aucun champ date mesuré"
    bad = {
        k: m
        for k, m in seen.items()
        if m["scroll"] > 0 or m["foot"] > 0 or m["over"] or m["native"]
    }
    assert not bad, f"à {NARROW} px : {bad}"
    # un panneau ouvert sans son contexte peut demander une ressource absente : seules les
    # erreurs JavaScript comptent ici
    errors = [p for p in narrow.problems if p.startswith("JS")]
    assert errors == [], errors
