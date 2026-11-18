"""L'écran Budget dans un vrai navigateur : le reste à dépenser et sa courbe, « Mon budget » (les
charges fixes dans l'ordre du mois, chaque catégorie suivie à une seule place), la fiche d'une
catégorie, « Régler », le mois en détail, les revenus attendus saisis avec Face ID, « Reprendre »
un dépassement sur une autre catégorie pour ce mois seulement, et rien qui dépasse sur un petit,
un moyen ou un grand téléphone."""

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
    page.evaluate(f'document.querySelector(\'[data-a="cat"][data-v="{category}"]\')?.click()')
    page.wait_for_selector("#sheet .how-seg")
    page.locator('#sheet [data-a="f-how"][data-v="month"]').click()
    page.fill("#f-amt", value)
    page.locator('#sheet [data-a="f-save"]').click()
    page.wait_for_selector("html:not(.sheet-open)")


def _subs(page: Any) -> None:
    """Les abonnements repérés, depuis le bas de « Régler »."""
    open_tab(page, "budget")
    page.locator('#budBody [data-a="plan"]').first.click()
    page.locator('#sheet [data-a="subs"]').click()
    page.wait_for_selector("#sheet #subs")


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
    # chaque catégorie suivie a une seule place dans Mon budget
    shown = page.eval_on_selector_all(
        '#budCats [data-a="cat"]', "(xs) => xs.map((x) => x.dataset.v)"
    )
    assert shown
    assert len(shown) == len(set(shown))
    assert page.locator("#trend .mcol").count() >= 1  # la tendance, ouverte en bas
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


def test_a_savings_target_is_set_from_the_month_detail(page: Any) -> None:
    cats = _get(page, "/finance/categories")["items"]
    saving = next(c for c in cats if c["active"] and c["group"] == "savings")
    open_tab(page, "budget")
    page.locator('#budBody [data-a="bhead"]').click()
    page.wait_for_selector('#sheet [data-a="plan"]')
    page.locator('#sheet .link-row[data-a="plan"]').click()
    page.wait_for_selector(f"#plan-{saving['id']}")
    page.fill(f"#plan-{saving['id']}", "300")
    page.locator('#sheet [data-a="plan-save"]').click()
    page.wait_for_selector("html:not(.sheet-open)")
    plan = _budget(page)["plan"]
    assert float(plan["savings"]["display"]) >= 300
    assert saving["id"] in {x["category"] for x in plan["savings_lines"]}
    # la catégorie d'épargne s'ouvre depuis le mois en détail, avec sa cible
    page.locator('#budBody [data-a="bhead"]').click()
    page.locator(f'#sheet [data-a="cat"][data-v="{saving["id"]}"]').click()
    page.wait_for_selector("#f-amt")
    assert page.input_value("#f-amt") == "300"
    page.locator('#sheet [data-a="sheet-close"]').click()
    page.wait_for_selector("html:not(.sheet-open)")
    assert page.problems == []


def test_a_detected_subscription_is_renamed_and_removed_from_the_budget(page: Any) -> None:
    found = page.evaluate(
        "fetch('/api/finance/recurring/refresh', {method: 'POST'}).then((r) => r.json())"
    )
    items = [x for x in found["items"] if x["active"]]
    assert items, "les données de démonstration ont des abonnements"
    sub = items[0]
    _subs(page)
    page.locator(f'#subs [data-a="sub"][data-v="{sub["key"]}"]').click()
    page.wait_for_selector("#sub-name")
    page.fill("#sub-name", "Nom corrigé")
    page.locator('#sheet [data-a="sub-save"]').click()
    page.wait_for_selector("html:not(.sheet-open)")
    item = next(x for x in _get(page, "/finance/recurring")["items"] if x["key"] == sub["key"])
    assert (item["label"], item["found_label"]) == ("Nom corrigé", sub["found_label"])
    _subs(page)
    page.locator(f'#subs [data-a="sub"][data-v="{sub["key"]}"]').click()
    page.locator('#sheet [data-a="sub-hide"]').click()
    page.wait_for_selector("html:not(.sheet-open)")
    after = _get(page, "/finance/recurring")
    assert sub["key"] in {x["key"] for x in after["removed"]}
    _subs(page)
    page.wait_for_selector(f'#subs [data-a="sub-show"][data-v="{sub["key"]}"]')
    page.locator(f'#subs [data-a="sub-show"][data-v="{sub["key"]}"]').click()
    page.wait_for_function(
        "fetch('/api/finance/recurring').then((r) => r.json()).then((d) => !d.removed.length)"
    )
    assert page.problems == []


def test_a_fixed_target_is_set_per_year_from_the_plan_and_shows_on_the_month(page: Any) -> None:
    cats = _get(page, "/finance/categories")["items"]
    lines = {x["category"]: x for x in _budget(page)["lines"]}
    fixed = next(
        c
        for c in cats
        if c["active"]
        and c["group"] == "fixed"
        and (c.get("mode") or "target") == "target"
        and not (lines.get(c["id"]) or {}).get("yearly")
    )
    open_tab(page, "budget")
    page.locator('#budBody [data-a="plan"]').first.click()
    page.wait_for_selector(f"#plan-{fixed['id']}")
    page.fill(f"#plan-{fixed['id']}", "1200")
    toggle = page.locator(f'#sheet [data-a="plan-cad"][data-v="{fixed["id"]}"]')
    assert toggle.get_attribute("aria-pressed") == "false"
    toggle.click()
    assert toggle.get_attribute("aria-pressed") == "true"
    page.locator('#sheet [data-a="plan-save"]').click()
    page.wait_for_selector("html:not(.sheet-open)")
    line = next(x for x in _budget(page)["lines"] if x["category"] == fixed["id"])
    assert float(line["yearly"]["target"]["display"]) == 1200
    assert page.problems == []


def test_a_category_set_per_year_from_its_card_goes_to_per_year(page: Any) -> None:
    lines = _budget(page)["lines"]
    var = next(x for x in lines if x["group"] == "variable" and x["target"] and not x.get("yearly"))
    open_tab(page, "budget")
    page.locator(f'#budCats [data-a="cat"][data-v="{var["category"]}"]').click()
    page.wait_for_selector("#f-amt")
    page.locator('#sheet [data-a="f-how"][data-v="year"]').click()
    page.fill("#f-amt", "2400")
    assert "200" in page.inner_text("#sheet .how-per")  # soit 200 par mois
    page.locator('#sheet [data-a="f-save"]').click()
    page.wait_for_selector("html:not(.sheet-open)")
    line = next(x for x in _budget(page)["lines"] if x["category"] == var["category"])
    assert float(line["yearly"]["target"]["display"]) == 2400
    # elle passe dans « Par an », une seule fois
    page.wait_for_function(
        f"""[...document.querySelectorAll('#budCats [data-a="cat"]')]
            .filter((x) => x.dataset.v === "{var["category"]}").length === 1"""
    )
    assert "par an" in page.inner_text("#budCats").lower()
    assert page.problems == []


def test_a_new_category_with_a_target_keeps_its_target_to_confirm(page: Any) -> None:
    open_tab(page, "budget")
    page.locator('#budBody [data-a="plan"]').first.click()
    page.locator('#sheet [data-a="cat-new"]').click()
    page.fill("#f-name", "Frais du jardin")
    page.locator('#sheet [data-a="f-how"][data-v="year"]').click()
    page.fill("#f-amt", "600")
    page.locator('#sheet [data-a="f-save"]').click()
    page.wait_for_selector("#sheet .hint >> text=Il reste à valider sa cible")
    page.locator('#sheet [data-a="f-save"]').click()
    page.wait_for_selector("html:not(.sheet-open)")
    cats = _get(page, "/finance/categories")["items"]
    made = next(c for c in cats if c["name"] == "Frais du jardin")
    line = next(x for x in _budget(page)["lines"] if x["category"] == made["id"])
    assert float(line["yearly"]["target"]["display"]) == 600
    assert page.problems == []


def test_the_flow_shows_in_place_of_the_list(page: Any) -> None:
    open_tab(page, "budget")
    page.locator('#budCats [data-a="bview"][data-v="flow"]').click()
    page.wait_for_selector("#budCats svg")
    assert page.locator("#budCats .fx-row").count() == 0
    page.locator('#budCats [data-a="bview"][data-v="cats"]').click()
    page.wait_for_selector("#budCats .crow, #budCats .fx-row")
    assert page.problems == []
