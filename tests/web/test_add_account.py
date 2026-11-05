"""Ajouter un compte en trois étapes (type, plateforme, comment le hub reçoit ses données) : la
connexion se crée en passant, ses identifiants partent chiffrés et le compte se crée avec Face ID ;
un portefeuille rejoint la connexion « Cours et cryptos »."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from tests.web.test_app_mobile import browse, instance  # noqa: F401 (fixture du module)


@pytest.fixture(scope="module")
def page(instance: tuple[str, str]) -> Iterator[Any]:  # noqa: F811
    with browse(*instance) as pg:
        yield pg


def _get(page: Any, path: str) -> Any:
    return page.evaluate(f"fetch('/api{path}').then((r) => r.json())")


def _start(page: Any) -> Any:
    page.click('#tabs button[data-v="accueil"]')
    page.locator('#accueil [data-a="settings"]').click()
    page.locator('#rubrics [data-a="rubric"][data-v="accounts"]').click()
    page.wait_for_selector('#sources [data-rubric="accounts"]:not(.off-rubric)', state="attached")
    page.click("#acct-add")
    # une page à part, son titre, l'étape 1 ; Comptes n'est plus affiché
    page.wait_for_selector("#acct-editor:not([hidden]):not(.off-rubric)")
    assert page.inner_text("#t-sources") == "Ajouter un compte"
    assert page.locator("#fresh-list").is_hidden()
    return page.locator("#acct-editor")


def _back_on_accounts(page: Any) -> None:
    page.wait_for_selector('#sources [data-rubric="accounts"]:not(.off-rubric)', state="attached")
    assert page.inner_text("#t-sources") == "Comptes"
    assert page.locator("#acct-editor").is_hidden()


def test_a_platform_account_brings_its_connection(page: Any) -> None:
    ed = _start(page)
    ed.get_by_role("button", name="Crypto : plateforme").click()
    ed.get_by_role("button", name="KuCoin").click()
    assert "Étape 3 sur 3" in ed.inner_text()
    for key in ("api_key", "api_secret", "passphrase"):
        page.fill(f"#aa-secret-{key}", f"test-{key}")
    ed.get_by_role("button", name="Brancher et créer le compte avec Face ID").click()
    _back_on_accounts(page)
    assert "KuCoin branché" in page.inner_text("#acct-msg")

    conn = next(
        c for c in _get(page, "/collectors/connections")["items"] if c["connector"] == "kucoin"
    )
    assert (conn["id"], conn["ready"]) == ("kucoin", True)
    refs = {a["external_ref"] for a in _get(page, "/finance/accounts")["items"]}
    assert "crypto:kucoin" in refs

    # un deuxième compte KuCoin ne redemande pas l'accès : la connexion sert déjà
    ed = _start(page)
    ed.get_by_role("button", name="Crypto : plateforme").click()
    ed.get_by_role("button", name="KuCoin").click()
    assert "déjà branché" in ed.inner_text()
    ed.get_by_role("button", name="Fermer").click()
    _back_on_accounts(page)
    assert page.problems == []


def test_the_page_starts_over_each_time(page: Any) -> None:
    ed = _start(page)
    ed.get_by_role("button", name="Crypto : portefeuille").click()
    assert "Étape 2 sur 3" in ed.inner_text()
    page.go_back()
    _back_on_accounts(page)
    ed = _start(page)
    assert "Étape 1 sur 3" in ed.inner_text()
    ed.get_by_role("button", name="Annuler").click()
    _back_on_accounts(page)
    assert page.problems == []


def test_a_wallet_joins_the_prices_connection(page: Any) -> None:
    ed = _start(page)
    ed.get_by_role("button", name="Crypto : portefeuille").click()
    ed.get_by_role("button", name="Ethereum et réseaux EVM").click()
    page.fill("#aa-wname", "Rabby")
    assert "crypto:rabby" in ed.inner_text()
    page.fill("#aa-wkeys", "0x" + "1" * 40)
    ed.get_by_label("Base").check()
    ed.get_by_role("button", name="Ajouter avec Face ID").click()
    _back_on_accounts(page)
    assert "Rabby ajouté" in page.inner_text("#acct-msg")

    market = next(
        c for c in _get(page, "/collectors/connections")["items"] if c["connector"] == "market"
    )
    (w,) = [w for w in market["settings"]["wallets"] if w["account"] == "crypto:rabby"]
    assert (w["asset"], w["addresses"], w["networks"]) == (
        "ETH",
        ["0x" + "1" * 40],
        ["ethereum", "base"],
    )
    refs = {a["external_ref"] for a in _get(page, "/finance/accounts")["items"]}
    assert "crypto:rabby" in refs
    assert page.problems == []
