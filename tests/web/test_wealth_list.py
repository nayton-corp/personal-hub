"""La liste Comptes / Actifs du patrimoine dans un vrai navigateur : le tri (un critère, un ordre),
la pastille du rendement, et les lignes masquées (à la main avec l'œil, ou à zéro) qui quittent
la liste sans quitter le total."""

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

ROWS = "#patrimoine .list .row-title"


@pytest.fixture(scope="module")
def instance_extra() -> Callable[[dict[str, str]], None]:
    """Un compte vide : il vaut zéro, il se masque tout seul."""

    def add(env: dict[str, str]) -> None:
        _hub(env, "finance", "accounts", "add", "Compte fermé fictif", "--institution", "Banque",
             "--external-ref", "test:vide", "--kind", "securities")  # fmt: skip

    return add


@pytest.fixture(scope="module")
def page(instance: tuple[str, str]) -> Iterator[Any]:  # noqa: F811
    with browse(*instance) as pg:
        yield pg


def _list(page: Any) -> Any:
    open_tab(page, "patrimoine")
    page.wait_for_selector("#detailHead .sort-btn")
    page.locator('#detailHead [data-a="w-view"][data-v="acc"]').click()
    page.wait_for_timeout(200)
    return page


def _titles(page: Any) -> list[str]:
    return [t.strip() for t in page.locator(ROWS).all_inner_texts()]


def _total(page: Any) -> int:
    kpis = page.evaluate("fetch('/api/finance/kpis').then((r) => r.json())")
    return int(kpis["net_worth"]["minor"])


def _close(page: Any) -> None:
    page.keyboard.press("Escape")
    page.wait_for_timeout(250)


def test_the_sort_has_a_criterion_and_an_order(page: Any) -> None:
    _list(page)
    page.locator('#detailHead [data-a="w-sort"]').click()
    page.locator('#sheet [data-a="w-sort-by"][data-v="az"]').click()
    names = _titles(page)
    assert names == sorted(names, key=str.casefold)
    assert "Nom" in page.inner_text("#detailHead .sort-btn")
    page.locator('#detailHead [data-a="w-sort"]').click()
    page.locator('#sheet [data-a="w-sort-dir"][data-v="desc"]').click()
    _close(page)
    assert _titles(page) == list(reversed(names))
    saved = page.evaluate("JSON.parse(localStorage.getItem('hub.wealth'))")
    assert (saved["sort"], saved["dir"]) == ("az", "desc")
    # tous les critères ont leur deux ordres ; « Gain en % » est nouveau
    page.locator('#detailHead [data-a="w-sort"]').click()
    crit = page.locator('#sheet [data-a="w-sort-by"]').evaluate_all(
        "(b) => b.map((x) => x.dataset.v)"
    )
    assert crit == ["val", "gain", "pct", "az"]
    assert page.locator('#sheet [data-a="w-sort-dir"]').count() == 2
    page.locator('#sheet [data-a="w-sort-by"][data-v="val"]').click()
    assert page.problems == []


def test_the_return_pill_says_up_or_down_without_colour_alone(page: Any) -> None:
    _list(page)
    up, down, flat = page.evaluate("""async () => {
      const m = await import('/d/finance/wlist.js');
      return [m.pill(0.0791), m.pill(-0.093), m.pill(0)];
    }""")
    for html, words in ((up, ("▲", "pos", "7,9 %")), (down, ("▼", "neg", "9,3 %"))):
        for w in words:
            assert w in html
    assert "zero" in flat
    for arrow in ("▲", "▼"):
        assert arrow not in flat


def test_an_empty_account_leaves_the_list_but_not_the_total(page: Any) -> None:
    _list(page)
    assert "Compte fermé fictif" not in _titles(page)
    foot = page.inner_text("#patrimoine .list-foot")
    assert "1 compte masqué" in foot
    page.locator("#patrimoine .list-foot").click()
    page.wait_for_selector('#sheet [data-a="w-mute"]')
    assert "masqué car à zéro" in page.inner_text("#sheet")
    _close(page)
    # l'interrupteur « à zéro » coupé, le compte revient
    page.locator('#detailHead [data-a="w-sort"]').click()
    page.locator('#sheet [data-a="w-zero"]').click()
    _close(page)
    assert "Compte fermé fictif" in _titles(page)
    page.locator('#detailHead [data-a="w-sort"]').click()
    page.locator('#sheet [data-a="w-zero"]').click()
    _close(page)
    assert "Compte fermé fictif" not in _titles(page)


def test_the_eye_hides_any_account_completely_and_keeps_it_counted(page: Any) -> None:
    _list(page)
    total = _total(page)
    hero = page.inner_text("#hero")
    name = _titles(page)[0]
    page.locator('#detailHead [data-a="w-sort"]').click()
    page.locator('#sheet [data-a="w-mutes"]').click()
    eye = page.locator('#sheet [data-a="w-mute"]').first
    assert eye.get_attribute("aria-pressed") == "false"
    eye.click()
    assert page.locator('#sheet [data-a="w-mute"]').first.get_attribute("aria-pressed") == "true"
    _close(page)
    # plus du tout dans la liste : ni grisée ni transparente
    assert name not in _titles(page)
    assert name not in page.inner_text("#patrimoine .list")
    assert "2 comptes masqués" in page.inner_text("#patrimoine .list-foot")
    assert _total(page) == total
    assert page.inner_text("#hero") == hero
    saved = page.evaluate("JSON.parse(localStorage.getItem('hub.wealth'))")
    assert len(saved["muted"]) == 1
    page.locator("#patrimoine .list-foot").click()
    page.locator('#sheet [data-a="w-mute"][aria-pressed="true"]:not([disabled])').click()
    _close(page)
    assert name in _titles(page)
    assert page.problems == []


def test_an_old_gain_sort_becomes_the_gain_in_francs(page: Any) -> None:
    open_tab(page, "patrimoine")
    page.evaluate("localStorage.setItem('hub.wealth', JSON.stringify({ sort: 'chg' }))")
    page.reload()
    _list(page)
    assert page.inner_text("#detailHead .sort-btn").split() == ["Gain", "↓"]
    page.evaluate("localStorage.removeItem('hub.wealth')")


def test_a_line_says_its_gain_since_purchase_not_a_period_rate(page: Any) -> None:
    """16/11 : Bitcoin +1 438 sur 7 666 affichait 172,4 % (le % d'une période rapporté à un capital
    moyen minuscule). Une ligne dit son gain depuis l'achat, sur le prix de revient ; sans prix
    de revient pour une position, ni francs ni pastille."""
    _list(page)
    got = page.evaluate("""async () => {
      const m = await import('/d/finance/wcrypto.js');
      const btc = { isin: 'BTC', value: 7666, cost: 6228 }, cash = { value: 120 };
      return {
        one: m.buyGain([btc, cash]),
        two: m.buyGain([btc, { isin: 'ETH', value: 334, cost: 372 }]),
        blind: m.buyGain([btc, { isin: 'ETH', value: 334, cost: null }]),
        cash: m.buyGain([cash]),
        pool: m.buyGain([btc], {
          cost: { minor: 500000, currency: 'CHF' }, unrealized: { minor: 50000, currency: 'CHF' },
        }),
      };
    }""")
    assert got["one"]["gain"] == 1438
    assert got["one"]["pct"] == pytest.approx(1438 / 6228)
    assert got["two"]["gain"] == 8000 - 6600
    assert got["blind"] is None
    assert got["cash"] is None
    assert got["pool"]["pct"] == pytest.approx(0.1)
    assert "Gain depuis l'achat" in page.inner_text("#patrimoine .list-cap")
