"""La refonte de Finance dans un vrai navigateur : le budget en pourcentage, la sélection
multiple du journal, les biens hors comptes, les frais des fonds, la mise en route, et aucun
écran qui dépasse sur un petit ou un grand téléphone."""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Iterator
from typing import Any

import pytest

from tests.web.test_app_mobile import (  # noqa: F401 (fixture du module)
    HEIGHT,
    TABS,
    WIDTH,
    _hub,
    browse,
    instance,
    open_settings,
    open_tab,
)

FUND = "IE00B3RBWM25"  # ISIN fictif, forme valide


@pytest.fixture(scope="module")
def instance_extra() -> Callable[[dict[str, str]], None]:
    """Un compte de titres, pour qu'un fonds puisse y être déposé."""

    def add(env: dict[str, str]) -> None:
        _hub(env, "finance", "accounts", "add", "Titres fictifs", "--institution", "Courtier",
             "--external-ref", "test:invest", "--kind", "securities")  # fmt: skip

    return add


@pytest.fixture(scope="module")
def page(instance: tuple[str, str]) -> Iterator[Any]:  # noqa: F811
    with browse(*instance) as pg:
        yield pg


def _get(page: Any, path: str) -> Any:
    return page.evaluate(f"fetch('/api{path}').then((r) => r.json())")


def _overflow(page: Any) -> int:
    return int(page.evaluate("document.documentElement.scrollWidth - window.innerWidth"))


@pytest.mark.parametrize("width", [320, 390])
def test_no_screen_overflows_on_a_small_or_a_large_phone(page: Any, width: int) -> None:
    page.set_viewport_size({"width": width, "height": HEIGHT})
    try:
        for tab in TABS:
            open_tab(page, tab)
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(300)
            assert _overflow(page) <= 0, f"{tab} dépasse à {width} px"
        open_tab(page, "patrimoine")
        for card in ("alloc", "rend"):
            page.locator(f'#patrimoine [data-a="w-card"][data-v="{card}"]').click()
            page.wait_for_selector("#sheet.tall")
            assert _overflow(page) <= 0, f"panneau {card} dépasse à {width} px"
            page.locator('#sheet [data-a="sheet-close"]').click()
    finally:
        page.set_viewport_size({"width": WIDTH, "height": HEIGHT})
    assert page.problems == []


def test_the_budget_reads_in_percent_of_each_budget(page: Any) -> None:
    open_tab(page, "budget")
    page.locator('#budCats [data-a="boff"]').click()  # sans cible, les catégories sont repliées
    page.locator('#budCats .crow[data-a="cat"]').first.click()
    page.fill("#t-input", "400")
    page.locator('#sheet [data-a="target-save"]').click()
    page.wait_for_selector("#budCats .crow .pbar.pc")
    shares = page.locator("#budCats .crow-top small").all_inner_texts()
    assert shares
    assert all(s.strip().endswith("%") for s in shares)
    # la barre est une part du budget de la ligne : jamais plus large que sa piste
    widths = page.evaluate(
        "[...document.querySelectorAll('#budCats .pbar.pc')]"
        ".map((b) => b.firstElementChild.offsetWidth <= b.offsetWidth + 1)"
    )
    assert all(widths)
    assert page.problems == []


def test_a_long_press_selects_entries_and_files_them_at_once(page: Any) -> None:
    open_tab(page, "journal")
    rows = page.locator('#jBody [data-a="tx"]')
    box = rows.nth(0).bounding_box()
    page.mouse.move(box["x"] + 40, box["y"] + box["height"] / 2)
    page.mouse.down()
    page.wait_for_timeout(650)
    page.mouse.up()
    page.wait_for_selector("#jsel")
    assert "1 sélectionnée" in page.inner_text("#jsel")
    assert not page.locator("#sheet").is_visible()  # la ligne ne s'est pas ouverte
    page.wait_for_timeout(750)  # le clic qui suit l'appui long est passé
    rows.nth(1).click()
    assert "2 sélectionnées" in page.inner_text("#jsel")
    picked = page.locator('#jBody [data-a="tx"].picked').evaluate_all(
        "(rows) => rows.map((r) => r.dataset.v)"
    )
    assert len(picked) == 2
    page.locator('#jsel [data-a="jsel-cat"]').click()
    page.wait_for_selector('#sheet [data-a="jsel-pick"]')
    assert "Classer 2 écritures" in page.inner_text("#sheet")
    choice = page.locator('#sheet [data-a="jsel-pick"]').first
    category = choice.get_attribute("data-v")
    choice.click()
    page.locator('#sheet [data-a="jsel-ok"]').click()
    page.wait_for_selector("#jsel", state="detached")
    entries = {e["id"]: e for e in _get(page, "/finance/entries?limit=200")["items"]}
    assert {entries[i]["category"]["id"] for i in picked} == {category}
    assert page.problems == []


def test_a_good_joins_the_wealth_without_touching_the_return(page: Any) -> None:
    before = _get(page, "/finance/kpis")
    open_settings(page, "finance")
    page.locator('#rubrics [data-a="rubric"][data-v="accounts"]').click()
    page.wait_for_selector("#good-list .empty")
    page.locator('#sources [data-a="good-add"]').click()
    page.fill("#good-name", "Voiture fictive")
    page.locator('#sheet [data-a="good-kind"][data-v="vehicle"]').click()
    page.fill("#good-value", "18000")
    page.locator('#sheet [data-a="good-save"]').click()
    page.wait_for_selector('#good-list [data-a="good-edit"]')
    assert "Voiture fictive" in page.inner_text("#good-list")
    assert _overflow(page) <= 0
    (good,) = _get(page, "/finance/goods")["items"]
    assert good["value"]["minor"] == 1_800_000
    after = _get(page, "/finance/kpis")
    assert after["net_worth"]["minor"] - before["net_worth"]["minor"] == 1_800_000
    page.locator('#sources [data-a="back"]').click()
    open_tab(page, "patrimoine")
    page.wait_for_selector("#patrimoine .wcards .sumcard")
    assert "Voiture fictive" in page.inner_text("#patrimoine")
    assert page.problems == []


def test_the_fees_card_asks_for_the_missing_rates(page: Any) -> None:
    day = (dt.date.today() - dt.timedelta(days=3)).isoformat()  # noqa: DTZ011
    held = (
        "date,account,instrument,name,kind,quantity,price,currency\n"
        f"{day},test:invest,{FUND},Fonds Monde,etf,10,100,CHF\n"
    )
    status = page.evaluate(
        "(body) => fetch('/api/finance/imports?name=positions.csv', {method: 'POST', body})"
        ".then((r) => r.status)",
        held,
    )
    assert status == 202
    page.reload()
    page.wait_for_selector("#tabs-start button")  # onglets dessinés (l'orbe, elle, est fixe)
    open_tab(page, "patrimoine")
    page.locator('#patrimoine [data-a="w-more"][data-v="fees"]').click()
    page.wait_for_selector('#sheet [data-a="fee-edit"]')
    first = page.locator('#sheet [data-a="fee-edit"]').first
    isin = first.get_attribute("data-v")
    first.click()
    page.fill("#fee-ter", "0.20")
    page.locator('#sheet [data-a="fee-save"]').click()
    page.wait_for_function(
        "(isin) => fetch('/api/finance/fees').then((r) => r.json())"
        ".then((f) => f.items.some((i) => i.isin === isin && i.ter_pct === '0.20'))",
        arg=isin,
    )
    assert _overflow(page) <= 0
    page.wait_for_timeout(600)  # le panneau se referme ou revient à la liste
    if page.locator("#sheet").is_visible():
        page.locator('#sheet [data-a="sheet-close"]').click()
        page.wait_for_timeout(400)
    # 0,20 % de 1 000 CHF : le coût est chiffré, une fois les frais relus par l'écran
    page.wait_for_function(
        '() => document.querySelector(\'#patrimoine [data-a="w-more"][data-v="fees"]\')'
        "?.innerText.includes('par an')"
    )
    # sans dividende ni intérêt reçu, la carte Revenus ne s'affiche pas
    assert page.locator('#patrimoine [data-a="w-more"][data-v="income"]').count() == 0
    assert page.problems == []


def test_the_first_steps_card_opens_and_goes_away(page: Any) -> None:
    open_tab(page, "apercu")
    page.wait_for_selector("#apercu .fv-card")
    page.locator('#apercu [data-a="fv-open"]').click()
    page.wait_for_selector("#sheet .fv-row")
    assert page.locator("#sheet .fv-row").count() == 6
    assert page.locator("#sheet .fv-row.done").count() >= 1  # le premier compte est là
    page.locator('#sheet [data-a="fv-done"]').click()
    page.wait_for_selector("#apercu .fv-card", state="detached")
    assert page.problems == []


def test_the_accounts_and_assets_tabs_stick_right_below_the_top_bar(page: Any) -> None:
    """La barre du haut grandit au défilement (le total apparaît) : les onglets restent dessous."""
    open_tab(page, "patrimoine")
    page.wait_for_selector("#detailHead .vtabs")
    page.evaluate("""() => { const l = document.querySelector('#wsecs .list');
      for (let i = 0; i < 20; i++) l.appendChild(l.firstElementChild.cloneNode(true)); }""")
    try:
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_selector("#pat-top.compact")
        page.wait_for_timeout(400)  # la hauteur du total s'anime
        top, tabs = page.evaluate("""() => [
          document.getElementById('pat-top').getBoundingClientRect().bottom,
          document.getElementById('detailHead').getBoundingClientRect().top]""")
        assert abs(tabs - top) <= 1, f"onglets à {tabs} px, barre du haut jusqu'à {top} px"
    finally:
        page.evaluate("window.scrollTo(0, 0)")
        open_tab(page, "accueil")


def test_turning_the_phone_puts_the_curve_in_full_screen(page: Any) -> None:
    open_tab(page, "patrimoine")
    page.wait_for_selector("#cw svg")
    try:
        page.set_viewport_size({"width": HEIGHT, "height": WIDTH})  # paysage
        page.wait_for_selector("#wland .land:not(.rot)")
        page.set_viewport_size({"width": WIDTH, "height": HEIGHT})  # retour en portrait
        page.wait_for_selector("#wland", state="detached")
    finally:
        page.set_viewport_size({"width": WIDTH, "height": HEIGHT})
        open_tab(page, "accueil")
    assert page.problems == []
