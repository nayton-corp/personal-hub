"""Écran « Catégories » (refonte du budget, lot Q) dans un vrai navigateur : la liste s'ouvre
depuis le Budget, une catégorie change de mode et une nouvelle se crée avec Face ID, son
identifiant donné par le hub."""

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


def _cats(page: Any) -> dict[str, Any]:
    items = page.evaluate("fetch('/api/finance/categories').then((r) => r.json())")["items"]
    return {c["id"]: c for c in items}


def _open_list(page: Any) -> None:
    open_tab(page, "budget")
    page.locator('#budBody [data-a="plan"]').first.click()
    page.locator('#sheet [data-a="cats"]').click()
    page.wait_for_selector('#sheet [data-a="cat-new"]')


def test_a_category_changes_mode_with_face_id(page: Any) -> None:
    _open_list(page)
    target = next(
        c
        for c in _cats(page).values()
        if c["active"] and c["group"] == "variable" and c["mode"] == "target"
    )
    page.locator(f'#sheet [data-a="cat-edit"][data-v="{target["id"]}"]').click()
    page.wait_for_selector("#sheet .how-seg")  # la fiche de la catégorie, comme depuis le Budget
    page.locator('#sheet [data-a="f-how"][data-v="tracked"]').click()
    assert "sans cible ni alerte" in page.inner_text("#sheet")
    page.get_by_role("button", name="Enregistrer avec Face ID").click()
    page.wait_for_selector("html:not(.sheet-open)")
    assert _cats(page)[target["id"]]["mode"] == "tracked"


def test_a_new_category_gets_its_id_from_the_hub(page: Any) -> None:
    _open_list(page)
    page.locator('#sheet [data-a="cat-new"]').click()
    page.fill("#f-name", "Cours de piano")
    page.locator('#sheet [data-a="f-more"]').click()
    page.get_by_role("radio", name="music").click()
    page.get_by_role("button", name="Créer avec Face ID").click()
    page.wait_for_selector("html:not(.sheet-open)")
    made = _cats(page)["cours-de-piano"]
    assert (made["name"], made["group"], made["icon"]) == ("Cours de piano", "variable", "music:0")


def test_the_icon_picker_is_a_compact_grid_with_the_current_icon_selected(page: Any) -> None:
    _open_list(page)
    page.locator('#sheet [data-a="cat-edit"]').first.click()
    page.locator('#sheet [data-a="f-more"]').click()
    page.wait_for_selector("#f-name")
    icons = page.locator('#sheet [aria-label="Icône"] [role="radio"]')
    assert page.locator('#sheet [aria-label="Icône"] [aria-checked="true"]').count() == 1
    assert page.locator('#sheet [aria-label="Teinte"] [aria-checked="true"]').count() == 1
    tops = icons.evaluate_all("(bs) => bs.map((b) => Math.round(b.getBoundingClientRect().top))")
    assert tops.count(tops[0]) >= 5  # cinq icônes au moins par ligne sur un téléphone
    # ouvrir sans rien toucher ne propose aucun changement d'icône
    assert page.locator('#sheet [data-a="f-save"]').is_disabled()
    assert "Tout est à jour" in page.inner_text("#sheet")
    page.locator('#sheet [data-a="sheet-close"]').click()
    page.wait_for_selector("html:not(.sheet-open)")
