"""L'orbe de l'app, au centre de la barre du bas : toucher ouvre la conversation, l'assistant
répond par le hub, une réponse arrivée ailleurs sort dans une carte de verre qui reste, et une
orbe sans assistant le dit."""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from typing import Any

import pytest

from hub.core.assistant_link import AssistantLink
from hub.core.context import HubContext
from hub.core.registry import Registry
from hub.platform.settings import Paths, Secrets, Server, Settings
from tests.support.demo_domain import DemoDomain
from tests.web.test_app_mobile import ROOT, _free_port, bootstrap, browse, serve

HISTORY = [
    {
        "kind": "talk",
        "at": "2026-10-31T07:12:00+00:00",
        "text": "Le lave-vaisselle affiche E24",
        "answer": "Problème de vidange : nettoie le filtre.",
        "voice": True,
    },
]


class SlowAssistant:
    """Un assistant qui réfléchit un peu : le temps de quitter la conversation."""

    def __call__(
        self, method: str, url: str, data: bytes | None, mime: str, timeout: int
    ) -> tuple[int, bytes]:
        if url.endswith("/health"):
            return 200, json.dumps({"voice": "ok"}).encode()
        if "/history" in url:
            return 200, json.dumps({"items": HISTORY, "waiting": []}).encode()
        time.sleep(1.5)
        text = json.loads(data or b"{}")["text"]
        answer = {"answer": f"Tu as demandé : {text}", "done": [], "proposals": [], "confirm": None}
        return 200, json.dumps(answer).encode()


@pytest.fixture(scope="module")
def hub(tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[HubContext, str]]:
    import pyrage

    home = tmp_path_factory.mktemp("orbe")
    key = home / "age.key"
    key.write_text(f"{pyrage.x25519.Identity.generate()}\n")
    port = _free_port()
    origin = f"http://localhost:{port}"
    settings = Settings(
        paths=Paths(**{k: home / k for k in ("data", "inbox", "archive", "backup")}),
        server=Server(public_origin=origin, web_root=ROOT / "hub" / "web"),
        secrets=Secrets(age_key_file=key),
    )
    ctx = HubContext.build(settings, Registry([DemoDomain(settings.paths.data)]))
    ctx.migrate_all()
    with serve(ctx, port):
        yield ctx, origin
    ctx.dispose()


@pytest.fixture(scope="module")
def page(hub: tuple[HubContext, str]) -> Iterator[Any]:
    ctx, origin = hub
    ctx.assistant = AssistantLink("http://assistant:8770", SlowAssistant())
    with browse(origin, bootstrap(ctx)) as pg:
        yield pg


def test_tapping_the_orb_opens_the_conversation(page: Any) -> None:
    orb = page.locator("#orb")
    orb.wait_for()
    assert orb.locator("canvas").count() == 1
    orb.click()
    page.wait_for_selector("#assistant:not([hidden])")
    assert page.locator("#orb").get_attribute("aria-current") == "page"
    page.wait_for_selector("#chat .bot")
    assert "nettoie le filtre" in page.inner_text("#chat")
    assert "dit · " in page.inner_text("#chat .me")
    page.fill("#ask", "Combien en courses ?")
    page.press("#ask", "Enter")
    page.wait_for_selector("#chat .typing")
    page.wait_for_selector("#chat .bot >> text=Tu as demandé : Combien en courses ?")
    assert page.problems == []


def test_an_answer_that_arrives_elsewhere_waits_in_a_glass_card(page: Any) -> None:
    page.locator("#orb").click()
    page.wait_for_selector("#assistant:not([hidden])")
    page.locator('#suggest [data-v="Quoi de neuf ?"]').click()
    page.click('#tabs button[data-v="accueil"]')
    card = page.locator("#orbAnswer")
    card.wait_for(state="visible", timeout=10_000)
    assert "Tu as demandé : Quoi de neuf ?" in card.inner_text()
    assert page.locator("#orb .dot").is_visible()
    page.wait_for_timeout(500)
    assert card.is_visible()  # elle attend qu'on la lise
    card.locator('[data-a="assistant-open"]').click()
    page.wait_for_selector("#assistant:not([hidden])")
    assert page.locator("#orbAnswer").is_hidden()
    assert page.locator("#orb .dot").is_hidden()
    assert page.problems == []


def test_without_an_assistant_the_orb_says_so(hub: tuple[HubContext, str], page: Any) -> None:
    hub[0].assistant = AssistantLink(None)
    page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")  # tout se relit
    page.locator("#orb").click()
    page.wait_for_selector("#chat .chat-note >> text=Aucun assistant")
    assert "hors ligne" in (page.locator("#orb").get_attribute("aria-label") or "")
    assert page.problems == []
