"""Le nouvel écran Budget (refonte du budget, lot B) dans un vrai navigateur : le reste à dépenser
et sa courbe, le mois en détail, les revenus attendus saisis avec Face ID, « Reprendre » un
dépassement sur une autre catégorie pour ce mois seulement, « À venir », et rien qui dépasse sur
un petit, un moyen ou un grand téléphone."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

import pytest

from tests.web.test_app_mobile import (  # noqa: F401 (fixture du module)
    HEIGHT,
    WIDTH,
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


def _budget(page: Any) -> Any:
    month = page.evaluate("new Date().toISOString().slice(0, 7)")
    return _get(page, f"/finance/budget?month={month}&period=m")


def _close(page: Any) -> None:
    page.locator('#sheet [data-a="sheet-close"]').click()
    page.wait_for_selector("html:not(.sheet-open)")


def _target(page: Any, category: str, value: str) -> None:
    page.evaluate(f"document.querySelector('[data-a=\"cat\"][data-v=\"{category}\"]')?.click()")
    page.wait_for_selector("#t-input")
    page.fill("#t-input", value)
    page.locator('#sheet [data-a="target-save"]').click()
    page.wait_for_selector("html:not(.sheet-open)")


def test_the_month_opens_on_what_is_left_and_its_curve(page: Any) -> None:
    open_tab(page, "budget")
    page.wait_for_selector("#budBody .bhero")
    b = _budget(page)
    head = page.inner_text("#budBody .bhero")
    if b["plan"]["rest"] is not None:
        assert "Reste à dépenser" in head
        assert "par jour" in head or "Dépassé" in head
    else:
        assert "Dépensé ce mois" in head
    assert page.locator("#budBody svg.bcurve").count() == 1
    assert len(b["daily"]) >= 1
    up = _get(page, f"/finance/budget/upcoming?month={b['month']}")
    assert page.locator("#upcoming").count() == (1 if up["items"] else 0)
    assert page.problems == []


def test_expected_income_is_set_with_face_id(page: Any) -> None:
    open_tab(page, "budget")
    page.locator('#budBody [data-a="bhead"]').click()
    page.wait_for_selector("#sheet .kv")
    assert "Revenus attendus" in page.inner_text("#sheet")
    page.locator('#sheet [data-a="bincome"]').click()
    page.wait_for_selector("#inc-input")
    page.fill("#inc-input", "6000")
    page.locator('#sheet [data-a="binc-save"]').click()
    page.wait_for_selector("html:not(.sheet-open)")
    plan = _budget(page)["plan"]
    assert plan["income_source"] == "set"
    assert plan["income"]["display"].startswith("6000")
    assert page.problems == []


def test_an_overspent_category_is_covered_by_another_for_this_month(page: Any) -> None:
    open_tab(page, "budget")
    page.wait_for_selector("#budCats")
    spent = sorted(
        (x for x in _budget(page)["lines"] if x["group"] == "variable" and x["count"]),
        key=lambda x: -float(x["spent"]["display"]),
    )
    over, donor = spent[0]["category"], spent[-1]["category"]
    off = page.locator('#budCats [data-a="boff"][aria-expanded="false"]')
    if off.count():
        off.click()
    _target(page, over, "1")
    _target(page, donor, "5000")
    for x in page.locator('#budBody [data-a="bdismiss"]').all():  # une carte « à classer » d'abord
        if x.get_attribute("data-v") != f"over:{over}":
            x.click()
    page.wait_for_selector(f'#budBody [data-a="bmove"][data-v="{over}"]')
    page.locator(f'#budBody [data-a="bmove"][data-v="{over}"]').click()
    page.wait_for_selector("#sheet .mv-row.on")
    assert "pour ce mois seulement" in page.inner_text("#sheet")
    page.locator('#sheet [data-a="bmv-save"]').click()
    page.wait_for_selector("html:not(.sheet-open)")
    line = next(x for x in _budget(page)["lines"] if x["category"] == over)
    assert float(line["target"]["display"]) >= float(line["spent"]["display"])
    assert line["state"] != "over"
    assert page.problems == []


@pytest.mark.parametrize("width", [320, 375, 390])
def test_the_budget_and_its_panels_fit_a_phone(page: Any, width: int) -> None:
    page.set_viewport_size({"width": width, "height": HEIGHT})
    over = "document.documentElement.scrollWidth - window.innerWidth"
    try:
        open_tab(page, "budget")
        page.wait_for_selector("#budBody .bhero")
        page.wait_for_load_state("networkidle")
        assert page.evaluate(over) <= 0, f"le budget dépasse à {width} px"
        page.locator('#budBody [data-a="bhead"]').click()
        page.wait_for_selector("#sheet .kv")
        assert page.evaluate(over) <= 0, f"le mois en détail dépasse à {width} px"
        sheet = page.evaluate(
            "(() => { const s = document.getElementById('sheet');"
            " return s.scrollWidth - s.clientWidth; })()"
        )
        assert sheet <= 0
        _close(page)
    finally:
        page.set_viewport_size({"width": WIDTH, "height": HEIGHT})
    assert page.problems == []
