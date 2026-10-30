"""L'écran Assistant (spec de l'écran §7) : l'historique d'une personne et les messages du foyer, ce qui est prévu, les
boutons Oui / Non / Annuler, et la voix (un faux Whisper, une fausse voix : le son ne va nulle part)."""

import base64
import contextlib
import json
import sqlite3
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta

from domia_assistant.assistant import Assistant
from domia_assistant.domia import Noting
from domia_assistant.engagements import Engagements
from domia_assistant.llm import ScriptedModel
from domia_assistant.memory import ACCEPTED, CANCELLED, OFFERED, REFUSED, Memory
from domia_assistant.server import serve
from domia_assistant.tools import build
from domia_assistant.voice import VoiceUnavailable, kind, with_brew
from tests.fakes import FakeDomia

NOW = datetime(2026, 10, 25, 19, 0, tzinfo=UTC)


def test_history_mixes_the_persons_talks_with_the_household_messages_in_order():
    memory = Memory(":memory:")
    memory.log("robin", None, "allume la cuisine", "C'est fait.", at=NOW, done=["Cuisine"])
    memory.log("alex", None, "secret", "ok", at=NOW + timedelta(minutes=1))
    memory.log(
        None, "salon", "éteins tout", "Je le fais pour toute la maison ?", at=NOW + timedelta(minutes=2), voice=True
    )
    memory.message("Demain", "Pluie dès 15 h.", at=NOW + timedelta(minutes=3))
    memory.log("robin", None, "vieux", "vieux", at=NOW - timedelta(days=9))

    mine = memory.history("robin", NOW - timedelta(days=7))
    assert [(i["kind"], i.get("text")) for i in mine] == [("talk", "allume la cuisine"), ("message", "Pluie dès 15 h.")]
    assert mine[0]["done"] == ["Cuisine"] and mine[0]["voice"] is False
    shared = memory.history(None, NOW - timedelta(days=7))
    assert [i["text"] for i in shared] == ["éteins tout", "Pluie dès 15 h."]
    assert shared[0]["voice"] is True
    assert memory.history("robin", NOW - timedelta(days=7), limit=1) == mine[-1:]


def test_an_old_database_gains_the_new_columns(tmp_path):
    path = tmp_path / "assistant.sqlite"
    old = sqlite3.connect(path)
    old.execute(
        "CREATE TABLE conversations (id INTEGER PRIMARY KEY, at TEXT NOT NULL, person TEXT, room TEXT, text TEXT NOT NULL, answer TEXT NOT NULL)"
    )
    old.execute(
        "INSERT INTO conversations (at, person, room, text, answer) VALUES (?, 'robin', NULL, 'bonjour', 'salut')",
        (NOW.isoformat(),),
    )
    old.commit()
    old.close()
    memory = Memory(path)
    memory.log("robin", None, "merci", "de rien", at=NOW + timedelta(minutes=1), voice=True, done=["x"])
    items = memory.history("robin", NOW - timedelta(days=1))
    assert [(i["text"], i["voice"], i["done"]) for i in items] == [("bonjour", False, []), ("merci", True, ["x"])]
    Memory(path)  # rouvrir ne rajoute rien


def test_every_notification_is_kept_for_the_conversation():
    domia = FakeDomia()
    memory = Memory(":memory:")
    noting = Noting(domia, memory)
    noting.notify("Prévu hier soir", "C'est fait : j'ai lancé le robot.")
    assert domia.notices == [("Prévu hier soir", "C'est fait : j'ai lancé le robot.")]
    assert [m["title"] for m in memory.messages(NOW - timedelta(days=365))] == ["Prévu hier soir"]
    assert noting.house() == domia.house()  # le reste passe tel quel


class FakeVoice:
    def __init__(self, heard="allume la cuisine", missing=None):
        self.heard = heard
        self.missing = missing
        self.got = []

    def available(self):
        return self.missing

    def transcribe(self, audio, mime):
        if self.missing:
            raise VoiceUnavailable(self.missing)
        self.got.append((audio, mime))
        return self.heard

    def speak(self, text):
        return ("dit:" + text).encode()


def start(voice=None):
    domia = FakeDomia()
    memory = Memory(":memory:")
    engagements = Engagements(domia, memory, None, "Europe/Zurich")
    assistant = Assistant(
        domia, ScriptedModel([]), memory, lambda: build(domia, None, memory, None), engagements=engagements
    )
    server = serve(assistant, "127.0.0.1", 0, ("127.0.0.1",), lambda: {}, voice)
    return domia, memory, server, f"http://127.0.0.1:{server.server_address[1]}"


def call(url, data=None, content_type="application/json"):
    body = data if isinstance(data, bytes) or data is None else json.dumps(data).encode()
    request = urllib.request.Request(
        url, data=body, method="GET" if data is None else "POST", headers={"Content-Type": content_type}
    )
    try:
        with urllib.request.urlopen(request) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def offer(memory, question):
    now = datetime.now(UTC)
    body = json.dumps({"what": "lancé le robot", "at": None, "after_away_min": 15})
    return memory.offer("ROBOT_AWAY", question, body, now + timedelta(days=1), now - timedelta(minutes=1))


def test_history_and_planned_routes_and_the_plan_buttons():
    _domia, memory, server, url = start()
    try:
        robot = offer(memory, "Je lance le robot pendant votre absence ?")
        rain = offer(memory, "Je ferme le store avant la pluie ?")
        call(url + "/talk", {"text": "allume la cuisine", "person": "robin"})
        status, history = call(url + "/history?person=robin&days=7")
        assert status == 200
        assert [i["text"] for i in history["items"]] == ["allume la cuisine"]
        assert [w["id"] for w in history["waiting"]] == [robot, rain]
        assert call(url + "/history")[1]["items"] == []  # sans personne : pas les échanges de robin

        assert call(url + f"/planned/{robot}", {"decision": "ACCEPT", "person": "robin"}) == (200, {"done": True})
        assert call(url + f"/planned/{rain}", {"decision": "REFUSE"})[0] == 200
        assert memory.engagement(robot)["state"] == ACCEPTED and memory.engagement(robot)["person"] == "robin"
        assert memory.engagement(rain)["state"] == REFUSED
        assert call(url + f"/planned/{rain}", {"decision": "ACCEPT"})[0] == 409  # déjà réglé
        assert call(url + f"/planned/{robot}", {"decision": "MAYBE"})[0] == 400

        status, planned = call(url + "/planned")
        assert [(p["id"], p["accepted"], p["after_away_min"]) for p in planned["planned"]] == [(robot, True, 15)]
        assert call(url + f"/planned/{robot}", {"decision": "CANCEL"})[0] == 200
        assert memory.engagement(robot)["state"] == CANCELLED
        assert memory.engagements(OFFERED) == []
    finally:
        server.shutdown()


def test_voice_is_transcribed_answered_and_spoken_and_the_sound_is_kept_nowhere():
    voice = FakeVoice()
    domia, memory, server, url = start(voice)
    try:
        status, answer = call(
            url + "/voice?person=robin&room=cuisine&correlation_id=api-1", b"\x00son", "audio/webm;codecs=opus"
        )
        assert status == 200
        assert answer["heard"] == "allume la cuisine"
        assert answer["answer"] == "C'est fait." and answer["done"] == ["Cuisine"]
        assert base64.b64decode(answer["speech"]["data"]) == b"dit:C'est fait."
        assert answer["speech"]["mime"] == "audio/mp4"
        assert voice.got == [(b"\x00son", "audio/webm")]
        assert domia.gestures[0][3] == "robin"
        [talk] = memory.history("robin", datetime.now(UTC) - timedelta(days=1))
        assert talk["voice"] is True and talk["text"] == "allume la cuisine"

        assert call(url + "/voice", b"x", "text/plain")[0] == 400
        with contextlib.suppress(urllib.error.URLError):  # trop gros : refusé sans être lu (400 ou la connexion coupée)
            assert call(url + "/voice", b"x" * (1024 * 1024 + 1), "audio/mp4")[0] == 400
        voice.heard = ""
        assert call(url + "/voice?person=robin", b"x", "audio/mp4")[1]["answer"] == "Je n'ai rien entendu."
    finally:
        server.shutdown()


def test_without_whisper_the_voice_says_so_and_writing_still_works():
    _, _, server, url = start(FakeVoice(missing="mlx-whisper n'est pas installé"))
    try:
        status, error = call(url + "/voice", b"x", "audio/mp4")
        assert status == 503 and error["code"] == "VOICE_UNAVAILABLE"
        assert call(url + "/talk", {"text": "allume la cuisine"})[0] == 200
    finally:
        server.shutdown()
    _, _, server, url = start(None)
    try:
        assert call(url + "/voice", b"x", "audio/mp4")[1]["code"] == "VOICE_UNAVAILABLE"
    finally:
        server.shutdown()


def test_sound_types():
    assert kind("audio/mp4") == "audio/mp4"
    assert kind("audio/webm;codecs=opus") == "audio/webm"
    assert kind("video/mp4") is None and kind(None) is None


def test_ffmpeg_from_homebrew_is_found_under_a_launch_agent():
    # le PATH minimal d'un LaunchAgent : Homebrew s'ajoute, une seule fois, et l'ordre de départ reste
    assert (
        with_brew("/usr/bin:/bin:/usr/sbin:/sbin") == "/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin:/usr/local/bin"
    )
    assert with_brew("/usr/local/bin:/usr/bin") == "/usr/local/bin:/usr/bin:/opt/homebrew/bin"
    assert with_brew("") == "/opt/homebrew/bin:/usr/local/bin"
