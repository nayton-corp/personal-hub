"""Savoir la maison (spec de l'assistant complet §4, §8, §9) : des lectures ciblées, sous un plafond, et aucune route de
Domia sans outil ni raison écrite."""

from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from domia_assistant import reading
from domia_assistant.memory import Memory
from domia_assistant.tools import Speaker, build
from tests.fakes import FakeDomia

COMPTE = Speaker(person="robin")
ROOT = Path(__file__).resolve().parents[1]
JOURNAL = [
    {"at": "2026-10-25T06:00:00Z", "type": "checkpoint", "checkpoint": {"instance": {"x": "y" * 50_000}}},
    {"at": "2026-10-25T06:00:01Z", "type": "timer_tick"},
    {
        "at": "2026-10-25T07:10:00Z",
        "type": "entity_change",
        "entity_change": {"entity_id": "light.salon_plafond", "new_state": {"state": "on"}},
    },
    {
        "at": "2026-10-25T07:12:00Z",
        "type": "command",
        "command": {
            "name": "LightAction",
            "origin": "UI",
            "args": {"action": "TURN_OFF", "light_id": "living_ceiling"},
        },
    },
    {
        "at": "2026-10-25T07:12:01Z",
        "type": "entity_change",
        "entity_change": {"entity_id": "light.salon_plafond", "new_state": {"state": "off"}},
    },
    {
        "at": "2026-10-25T07:30:00Z",
        "type": "entity_change",
        "entity_change": {"entity_id": "light.bureau", "new_state": {"state": "on"}},
    },
]


def tools(**kw):
    return tools_for(FakeDomia(**kw))


def tools_for(domia):
    return build(domia, None, None, None, plan=lambda *a: None, engagements=object())


def test_the_house_is_read_for_one_room_or_one_kind():
    box = tools()
    salon = box.run("house", {"room": "salon"}, COMPTE)
    assert [r["id"] for r in salon["rooms"]] == ["living"] and "people" not in salon
    lights = box.run("house", {"kind": "lights"}, COMPTE)
    assert all(set(r) == {"id", "name", "lights"} for r in lights["rooms"])
    assert "people" in box.run("house", {}, COMPTE)


def test_a_mistyped_argument_answers_an_error_instead_of_ending_the_turn():
    # au banc, le modèle a donné la pièce en objet : le tour s'arrêtait sur une exception
    assert "arguments invalides" in tools().run("house", {"room": {"name": "salon"}}, COMPTE)["error"]


def test_settings_give_an_index_then_one_object_with_its_meaning():
    box = tools()
    index = box.run("settings", {}, COMPTE)
    assert index["revision"] == 0 and index["rooms"][0]["lights"][0][0] == "living_ceiling"
    assert reading.size(index) < 2000
    lamp = box.run(
        "settings", {"kind": "light", "id": "living_ceiling", "explain": True, "field": "off_warning_sec"}, COMPTE
    )
    assert lamp["room"] == "living_room" and lamp["settings"]["ha_entity_id"] == "light.salon_plafond"
    assert "off_warning_sec" in lamp["aide"]
    room = box.run("settings", {"kind": "room", "id": "living_room"}, COMPTE)
    assert room["settings"]["lights"] == ["living_ceiling", "living_tv"]
    assert "error" in box.run("settings", {"kind": "light", "id": "nope"}, COMPTE)


def test_the_journal_is_read_in_aggregates_without_checkpoints():
    box = tools(journal=JOURNAL)
    out = box.run("activity", {"hours": 24}, COMPTE)
    assert out["gestes"][0]["geste"] == "LightAction" and out["gestes"][0]["light_id"] == "living_ceiling"
    salon = next(c for c in out["changements"] if c["entité"] == "light.salon_plafond")
    assert salon == {
        "entité": "light.salon_plafond",
        "objet": "living_ceiling",
        "changements": 2,
        "état": "off",
        "à": salon["à"],
    }
    assert reading.size(out) < 1500  # le point de reprise de 50 000 caractères n'y est pas
    one = box.run("activity", {"object": "office_lamp"}, COMPTE)
    assert [c["entité"] for c in one["changements"]] == ["light.bureau"] and one["gestes"] == []
    room = box.run("activity", {"room": "Salon"}, COMPTE)
    assert {c["entité"] for c in room["changements"]} == {"light.salon_plafond"}
    # un extrait du journal : ni tics ni points de reprise (59 Mo par jour sur la vraie maison), les entités visées
    domia = FakeDomia(journal=JOURNAL)
    tools_for(domia).run("activity", {"object": "office_lamp"}, COMPTE)
    assert domia.journal_asked == (["command", "entity_change"], ["light.bureau"])
    tools_for(domia).run("activity", {}, COMPTE)
    assert "light.bureau" in domia.journal_asked[1] and not [
        e for e in domia.journal_asked[1] if e.startswith("sensor.")
    ]


def test_why_says_the_state_the_gestures_and_the_situation():
    out = tools(journal=JOURNAL).run("why", {"object": "living_ceiling"}, COMPTE)
    assert out["situation"] == "DAY" and out["gestes"][0]["light_id"] == "living_ceiling"


def test_status_notifications_estimates_and_ha_entities():
    box = tools(
        notifications=[
            {
                "at": "2099-01-01T08:00:00Z",
                "title": "Pile faible",
                "message": "Bouton entrée",
                "status": "SENT",
                "kind": "BATTERY",
            }
        ]
    )
    status = box.run("system_status", {}, COMPTE)
    assert status["status"] == "DEGRADED" and status["alertes"][0]["code"] == "SENSOR_STALE"
    sent = box.run("notifications", {"services": True}, COMPTE)
    assert sent["envoyées"][0]["titre"] == "Pile faible" and sent["services"][0]["id"] == "mobile_app_iphone"
    assert {e["id"] for e in box.run("estimates", {}, COMPTE)} == {"salon_tv", "chambre_lit"}
    unused = box.run("ha_entities", {"unused": True}, COMPTE)
    assert unused and all("dans_domia" not in e for e in unused)
    assert "light.salon_plafond" not in {e["entity_id"] for e in unused}


def test_a_test_notification_goes_to_the_speaker_by_default():
    # mesuré à l'orbe : HA listait 5 services au nom de Robin, le modèle l'a envoyée à Kim puis inventé un service
    domia = FakeDomia()
    conf = domia.config()
    conf["config"]["people"] = [{"id": "person_n", "name": "Robin"}, {"id": "person_k", "name": "Kim"}]
    conf["config"]["notifications"] = {
        "recipients": [{"id": "r1", "name": "Robin IPhone 18 Pro", "service": "notify.mobile_app_robin"}]
    }
    domia.config = lambda: conf
    box = build(domia, None, None, None)
    assert box.get("test_notification").gesture
    assert box.run("test_notification", {}, Speaker(person="person_n")) == {"envoyée à": ["Robin IPhone 18 Pro"]}
    assert domia.gestures[-1] == ("POST", "/api/notify/test", {"service": "notify.mobile_app_robin"}, "person_n")
    assert box.run("test_notification", {"to": "iPhone de Robin"}, Speaker(person="person_k"))["envoyée à"]
    kim = box.run("test_notification", {}, Speaker(person="person_k"))
    assert "Kim" in kim["error"] and kim["destinataires"] == ["Robin IPhone 18 Pro"] and len(domia.gestures) == 2
    assert "error" in box.run("test_notification", {}, Speaker(person=None))


def test_the_radar_counts_as_a_gesture_only_when_its_value_changes():
    def report(at, value):
        return {
            "at": at,
            "type": "command",
            "command": {
                "name": "ReportEstimate",
                "origin": "EXTERNAL",
                "args": {"estimate_id": "chambre_lit", "value": value, "confidence": 0.99},
            },
        }

    lines = [
        report("2026-10-25T22:00:00Z", False),
        report("2026-10-25T22:00:30Z", False),
        report("2026-10-25T22:01:00Z", True),
        report("2026-10-25T22:01:30Z", True),
        report("2026-10-25T22:02:00Z", False),
    ]
    out = reading.activity(lines, ZoneInfo("Europe/Zurich"), {})
    assert [(g["at"][-5:], g["value"]) for g in out["gestes"]] == [
        ("23:00", False),
        ("23:01", True),
        ("23:02", False),
    ]  # heure locale
    assert out["gestes_en_tout"] == 3


def test_an_estimate_asked_by_person_gives_every_estimate():
    out = tools().run("estimates", {"id": "person_cebf8bc3"}, COMPTE)
    assert "n'est pas un modèle" in out["note"] and {e["id"] for e in out["estimations"]} == {"salon_tv", "chambre_lit"}


def test_every_read_stays_under_the_budget_and_says_how_to_narrow():
    long = [
        {"at": "2099-01-01T08:00:00Z", "title": f"Titre {i}", "message": "x" * 80, "status": "SENT"} for i in range(200)
    ]
    out = tools(notifications=long).run("notifications", {}, COMPTE)
    assert reading.size(out) <= reading.BUDGET_CHARS and "tronqué" in out
    assert out["envoyées"][-1]["titre"] == "Titre 199"  # les plus récentes restent
    assert reading.fit(list(range(5000)))["items"][-1] == 4999
    assert reading.size(reading.fit({"a": "x" * 10_000})) <= reading.BUDGET_CHARS
    box = tools(journal=JOURNAL)
    for name in (
        "house",
        "facts",
        "settings",
        "system_status",
        "estimates",
        "ha_entities",
        "activity",
        "situations",
        "observations",
    ):
        assert reading.size(box.run(name, {}, COMPTE)) <= reading.BUDGET_CHARS, name


def test_no_route_of_domia_is_impossible_for_the_assistant():
    routes = (ROOT / "domia_assistant/contract/api/routes.golden.txt").read_text(encoding="utf-8").split("\n")
    routes = [r for r in routes if r]
    coverage = yaml.safe_load((ROOT / "parity/coverage.yaml").read_text(encoding="utf-8"))
    missing = [r for r in routes if r not in coverage]
    assert not missing, f"des routes sans outil ni raison écrite dans assistant/parity/coverage.yaml : {missing}"
    assert not [r for r in coverage if r not in routes], "des lignes pour des routes qui n'existent plus"
    names = set(
        build(
            FakeDomia(), None, Memory(":memory:"), None, plan=lambda *a: None, engagements=object(), settings_write=True
        ).tools
    ) | {"search_library"}
    for route, line in coverage.items():
        assert len(line) == 1 and next(iter(line)) in ("tool", "later", "excluded"), route
        for name in line.get("tool", []):
            assert name in names, f"{route} : l'outil {name} n'existe pas"
