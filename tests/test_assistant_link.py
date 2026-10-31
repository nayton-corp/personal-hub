"""L'orbe de l'app parle à l'assistant de la maison par le hub : session de l'app seule, le hub
relaie la phrase, l'historique et le son, et dit clairement quand l'assistant manque."""

from __future__ import annotations

import json
import urllib.error

from fastapi.testclient import TestClient

from hub.core.assistant_link import AssistantLink
from hub.core.context import HubContext
from tests.finance.test_finance_api import app_session

ANSWER = {"answer": "Nettoie le filtre.", "done": [], "proposals": [], "confirm": None}


class FakeAssistant:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, bytes | None, str]] = []

    def __call__(
        self, method: str, url: str, data: bytes | None, mime: str, timeout: int
    ) -> tuple[int, bytes]:
        self.calls.append((method, url, data, mime))
        if url.endswith("/health"):
            return 200, json.dumps({"version": "x", "voice": "ok"}).encode()
        if "/history" in url:
            items = [
                {
                    "kind": "talk",
                    "at": "2026-10-31T08:00:00+00:00",
                    "text": "E24 ?",
                    "answer": "Vidange.",
                }
            ]
            return 200, json.dumps({"items": items, "waiting": []}).encode()
        if "/voice" in url:
            return 200, json.dumps({**ANSWER, "heard": "quoi de neuf", "speech": None}).encode()
        return 200, json.dumps(ANSWER).encode()


def linked(hub: HubContext, person: str | None = "nathan") -> FakeAssistant:
    fake = FakeAssistant()
    hub.assistant = AssistantLink("http://assistant:8770", fake)
    hub.settings.assistant.__dict__["person"] = person
    return fake


def test_only_the_app_session_talks_to_the_assistant(hub: HubContext, client: TestClient) -> None:
    linked(hub)
    assert client.post("/api/assistant/talk", json={"text": "salut"}).status_code == 401


def test_a_sentence_goes_to_the_assistant_and_its_answer_comes_back(
    hub: HubContext, client: TestClient
) -> None:
    fake = linked(hub)
    app_session(hub, client)
    r = client.post("/api/assistant/talk", json={"text": "  le lave-vaisselle affiche E24  "})
    assert r.status_code == 200
    assert r.json()["answer"] == "Nettoie le filtre."
    method, url, data, _mime = fake.calls[-1]
    assert (method, url) == ("POST", "http://assistant:8770/talk")
    assert json.loads(data or b"") == {
        "text": "le lave-vaisselle affiche E24",
        "person": "nathan",
        "client": "hub",
    }


def test_the_history_and_the_status_are_read_through_the_hub(
    hub: HubContext, client: TestClient
) -> None:
    fake = linked(hub)
    app_session(hub, client)
    assert client.get("/api/assistant/status").json() == {
        "configured": True,
        "ok": True,
        "voice": True,
    }
    items = client.get("/api/assistant/history?days=3").json()["items"]
    assert items[0]["answer"] == "Vidange."
    assert "person=nathan" in fake.calls[-1][1]
    assert "days=3" in fake.calls[-1][1]


def test_a_spoken_sentence_is_relayed_as_sound(hub: HubContext, client: TestClient) -> None:
    fake = linked(hub)
    app_session(hub, client)
    r = client.post(
        "/api/assistant/voice",
        content=b"\x1a\x45",
        headers={"Content-Type": "audio/webm;codecs=opus"},
    )
    assert r.status_code == 200
    assert r.json()["heard"] == "quoi de neuf"
    assert fake.calls[-1][2:] == (b"\x1a\x45", "audio/webm;codecs=opus")
    bad = client.post("/api/assistant/voice", content=b"x", headers={"Content-Type": "text/plain"})
    assert bad.status_code == 422


def test_without_an_assistant_the_app_is_told_plainly(hub: HubContext, client: TestClient) -> None:
    app_session(hub, client)
    assert client.get("/api/assistant/status").json() == {
        "configured": False,
        "ok": False,
        "voice": False,
    }
    r = client.post("/api/assistant/talk", json={"text": "salut"})
    assert r.status_code == 503
    assert r.json()["type"].endswith("assistant.unconfigured")


def test_an_assistant_that_sleeps_is_reported_unreachable(
    hub: HubContext, client: TestClient
) -> None:
    def down(*_args: object) -> tuple[int, bytes]:
        raise urllib.error.URLError("refusé")

    hub.assistant = AssistantLink("http://assistant:8770", down)
    app_session(hub, client)
    assert client.get("/api/assistant/status").json()["ok"] is False
    r = client.post("/api/assistant/talk", json={"text": "salut"})
    assert r.status_code == 503
    assert r.json()["type"].endswith("assistant.unreachable")
