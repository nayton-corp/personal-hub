"""Corrections du passage de test manuel (protocole QA) dans un vrai navigateur : les saisies de
montant, le Journal qui ne lit jamais deux fois la même page, ses totaux sur toute la période,
le masquage des montants dans les phrases, la correction d'une écriture, les écrans restés en
erreur, le plein écran et le retour."""

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


@pytest.fixture(scope="module")
def instance_extra() -> Callable[[dict[str, str]], None]:
    return lambda _env: None


@pytest.fixture(scope="module")
def page(instance: tuple[str, str]) -> Iterator[Any]:  # noqa: F811
    with browse(*instance) as pg:
        yield pg


def _get(page: Any, path: str) -> Any:
    return page.evaluate(f"fetch('/api{path}').then((r) => r.json())")


def _close(page: Any) -> None:
    page.locator('#sheet [data-a="sheet-close"]').click()
    page.wait_for_selector("html:not(.sheet-open)")


def _first_category(page: Any) -> None:
    open_tab(page, "budget")
    page.wait_for_selector("#budCats")
    page.locator('#budCats [data-a="cat"]').first.click()
    page.wait_for_selector("#sheet .how-seg, #f-amt")
    if not page.locator("#f-amt").count():  # suivie sans cible : on lui donne une cible
        page.locator('#sheet [data-a="f-how"][data-v="month"]').click()
    page.wait_for_selector("#f-amt")


def test_a_target_reads_decimals_and_refuses_what_is_not_an_amount(page: Any) -> None:
    _first_category(page)
    save = page.locator('#sheet [data-a="f-save"]')
    for typed in ("12.50", "1'250,50", "1 250"):
        page.fill("#f-amt", typed)
        assert page.locator("#sheet .err").count() == 0, typed
        assert save.is_enabled(), typed
    for typed in ("-300", "1e6", "12.345"):
        page.fill("#f-amt", typed)
        assert "Montant invalide" in page.inner_text("#sheet .err"), typed
        assert save.is_disabled(), typed
        assert page.input_value("#f-amt") == typed  # ce qui est tapé reste dans le champ
    _close(page)
    assert page.problems == []


def test_changing_month_or_year_keeps_the_typed_amount(page: Any) -> None:
    _first_category(page)
    page.locator('#sheet [data-a="f-how"][data-v="year"]').click()
    page.fill("#f-amt", "125")
    page.locator('#sheet [data-a="f-how"][data-v="month"]').click()
    assert page.input_value("#f-amt") == "125"
    page.locator('#sheet [data-a="f-how"][data-v="year"]').click()
    assert page.input_value("#f-amt") == "125"
    _close(page)


def test_more_entries_never_reads_the_same_page_twice(page: Any) -> None:
    open_tab(page, "journal")
    page.wait_for_selector('#jBody [data-a="jmore"]')
    # trois touchers dans la même trame : une seule lecture de la suite
    page.evaluate("""() => { const b = document.querySelector('#jBody [data-a="jmore"]');
        b.click(); b.click(); b.click(); }""")
    page.wait_for_function("document.querySelectorAll('#jBody .tx-row').length > 50")
    page.wait_for_load_state("networkidle")
    keys = page.evaluate(
        "[...document.querySelectorAll('#jBody .tx-row')].map((r) => r.dataset.v || r.outerHTML)"
    )
    assert len(keys) == len(set(keys))
    assert page.problems == []


def test_the_journal_totals_cover_the_whole_selection(page: Any) -> None:
    open_tab(page, "journal")
    first = _get(page, "/finance/entries?limit=50")
    t = first["totals"]
    assert first["next_cursor"]  # plus d'une page
    head = page.inner_text("#jBody .jsum")
    assert f"{t['count']} écritures" in head.replace("'", "").replace(" ", "")
    assert "affichées" not in head


def test_closed_eye_hides_amounts_written_in_sentences(page: Any) -> None:
    open_tab(page, "budget")
    page.locator('#budget [aria-label="Masquer les montants"]').first.click()
    try:
        page.wait_for_selector("body.hide-amounts")
        leaks = page.evaluate(
            r"""() => [...document.querySelectorAll(
                '#budget .crow-st, #budget .status, #budget .proj')].flatMap((n) => {
              const c = n.cloneNode(true);
              c.querySelectorAll('.money').forEach((m) => m.remove());
              return /\d{3}/.test(c.textContent) ? [c.textContent.trim()] : []; })"""
        )
        assert leaks == []
    finally:
        page.locator('#budget [aria-label="Afficher les montants"]').first.click()


def test_correcting_an_entry_offers_the_accounts_and_keeps_typing(page: Any) -> None:
    open_tab(page, "journal")
    page.locator("#jBody .tx-row").first.click()
    page.locator('#sheet [data-a="tx-correct"]').click()
    page.wait_for_selector("#corr-account_id")
    assert page.locator("#corr-account_id option").count() >= 1
    page.fill("#corr-reason", "ticket relu")
    page.locator("#corr-booking_date").focus()  # change de champ : rien n'est redessiné
    assert page.input_value("#corr-reason") == "ticket relu"
    assert page.evaluate("document.activeElement.id") == "corr-booking_date"
    _close(page)


def test_a_screen_left_on_an_error_offers_to_retry(page: Any) -> None:
    open_tab(page, "accueil")
    page.evaluate("() => {}")
    failed = {"n": 0}

    def fail_once(route: Any) -> None:
        if failed["n"] == 0:
            failed["n"] += 1
            route.fulfill(status=500, json={"title": "Erreur interne"})
        else:
            route.continue_()

    page.route("**/api/finance/budget?**", fail_once)
    try:
        # cache vidé, comme à l'expiration de la session
        page.evaluate("window.dispatchEvent(new Event('hub:auth'))")
        page.wait_for_selector("#shell:not([hidden])")
        open_tab(page, "budget")
        page.wait_for_selector('#budBody [data-a="retry"]')
        page.locator('#budBody [data-a="retry"]').click()
        page.wait_for_selector("#budBody .crow")
    finally:
        page.unroute("**/api/finance/budget?**")
    assert [p for p in page.problems if "500" not in p] == []
    page.problems.clear()


def test_the_back_gesture_closes_the_full_screen_curve(page: Any) -> None:
    open_tab(page, "patrimoine")
    page.locator('#patrimoine [data-a="w-display"]').click()
    page.locator('#sheet [data-a="w-full"][data-v="1"]').click()
    page.wait_for_selector("#wland svg")
    page.go_back()
    page.wait_for_selector("#wland", state="detached")
    assert page.is_visible("#patrimoine")
    assert page.problems == []
