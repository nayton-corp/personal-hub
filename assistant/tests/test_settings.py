"""Régler avec un Oui (spec de l'assistant complet §5, §11) : des changements typés posés sur la config lue, vérifiés
par Domia sans rien écrire, un résumé en unités de l'écran ; l'écriture seulement après le oui de la même personne,
sur la révision lue ; l'annulation, elle aussi avec un oui."""

import asyncio
from datetime import UTC, datetime, timedelta

from mcp.shared.memory import create_connected_server_and_client_session

from domia_assistant.assistant import Assistant
from domia_assistant.llm import ScriptedModel, call, calls, say
from domia_assistant.mcp_server import make_server
from domia_assistant.memory import Memory
from domia_assistant.settings import Draft, Settler, human
from domia_assistant.tools import Speaker, build
from tests.fakes import FakeDomia

COMPTE = Speaker(person="robin", client="client_phone")
SHORTER = {"op": "set", "kind": "room", "id": "hallway", "fields": {"vacant_after_sec": 120}}


def make(replies=()):
    domia, memory = FakeDomia(), Memory(":memory:")
    assistant = Assistant(
        domia,
        ScriptedModel(list(replies)),
        memory,
        lambda: build(domia, None, memory, None, settings_write=True),
        clock=lambda: 0.0,
    )
    return assistant, domia, memory


def config(domia):
    return domia.config()["config"]


def room(domia, id):
    return next(r for r in config(domia)["rooms"] if r["id"] == id)


def test_a_value_is_said_as_the_screen_says_it():
    assert (
        human(300, "vacant_after_sec") == "5 min" and human(5400, "x_sec") == "90 min" and human(7200, "x_sec") == "2 h"
    )
    assert human(45, "x_sec") == "45 s" and human(True, "enabled") == "oui" and human(None, "x") == "rien"


def test_changes_are_typed_and_never_carry_an_id():
    draft = Draft(FakeDomia().config()["config"])
    draft.change({"op": "set", "kind": "light", "id": "hallway_ceiling", "fields": {"off_warning_sec": 30, "a.b": 1}})
    assert draft.summary[0].startswith("Couloir › ") and "→ 30 s" in draft.summary[0]
    draft.change(
        {
            "op": "add",
            "kind": "light",
            "room": "office",
            "fields": {"name": "Applique", "ha_entity_id": "light.applique"},
        }
    )
    assert draft.summary[-1] == "ajout : lampe « Applique » dans Bureau"
    for bad in (
        {"op": "add", "kind": "light", "room": "office", "fields": {"id": "x"}},
        {"op": "add", "kind": "light", "fields": {}},
        {"op": "set", "kind": "light", "id": "nope", "fields": {"x": 1}},
        {"op": "jump", "kind": "light"},
    ):
        try:
            draft.change(bad)
            raise AssertionError(bad)
        except ValueError:
            pass


def test_a_setting_waits_for_a_yes_then_is_written_on_the_read_revision():
    assistant, domia, _memory = make([calls(call("propose_settings", {"changes": [SHORTER]})), say("ignoré")])
    asked = assistant.talk("éteins le couloir après 2 minutes", COMPTE)
    assert (
        asked["confirm"]
        and "vacant_after_sec" in asked["answer"]
        and "→ 2 min" in asked["answer"]
        and "Je l'applique ?" in asked["answer"]
    )
    assert room(domia, "hallway")["vacant_after_sec"] != 120 and domia.gestures == []  # vérifié, rien d'écrit
    done = assistant.talk("oui", COMPTE)
    assert done["answer"].startswith("C'est réglé") and done["done"] == ["réglage"]
    assert room(domia, "hallway")["vacant_after_sec"] == 120
    assert domia.gestures[-1] == ("PUT", "/api/config", None, "robin")


def test_no_yes_no_write_and_a_refused_setting_is_explained():
    assistant, domia, _ = make([calls(call("propose_settings", {"changes": [SHORTER]}))])
    assistant.talk("éteins le couloir après 2 minutes", COMPTE)
    assert assistant.talk("non", COMPTE)["answer"] == "D'accord, je ne fais rien." and domia.gestures == []
    settler = Settler(domia, Memory(":memory:"))
    refused = settler.propose([{**SHORTER, "fields": {"vacant_after_sec": -5}}], "robin")
    assert refused["error"] == "Domia refuse ce réglage" and "vacant_after_sec" in refused["messages"][0]


def test_apply_is_refused_for_another_person_too_late_or_after_a_change():
    domia, memory = FakeDomia(), Memory(":memory:")
    clock = [datetime(2026, 10, 25, 12, 0, tzinfo=UTC)]
    settler = Settler(domia, memory, now=lambda: clock[0])
    first = settler.propose([SHORTER], "robin")["proposition"]
    assert "error" in settler.apply(first, "kim")
    clock[0] += timedelta(minutes=16)
    assert "trop ancienne" in settler.apply(first, "robin")["error"]
    late = settler.propose([SHORTER], "robin")["proposition"]
    domia.config_put(config(domia), domia.config()["config_revision"], "kim")  # quelqu'un règle à l'écran
    assert "a changé" in settler.apply(late, "robin")["error"]
    assert settler.apply(late, "robin")["error"]  # une proposition ne s'applique pas deux fois non plus


def test_undo_proposes_the_state_before_and_also_waits_for_a_yes():
    domia, memory = FakeDomia(), Memory(":memory:")
    settler = Settler(domia, memory)
    before = room(domia, "hallway")["vacant_after_sec"]
    settler.apply(settler.propose([SHORTER], "robin")["proposition"], "robin")
    back = settler.undo("robin")
    assert f"2 min → {human(before, 'vacant_after_sec')}" in back["question"]
    settler.apply(back["proposition"], "robin")
    assert room(domia, "hallway")["vacant_after_sec"] == before


def test_an_added_object_is_undone_by_removing_the_one_domia_created():
    domia, memory = FakeDomia(), Memory(":memory:")
    settler = Settler(domia, memory)
    add = {
        "op": "add",
        "kind": "light",
        "room": "office",
        "fields": {"name": "Applique", "ha_entity_id": "light.applique", "dimmable": False},
    }
    settler.apply(settler.propose([add], "robin")["proposition"], "robin")
    assert [lamp["name"] for lamp in room(domia, "office")["lights"]][-1] == "Applique"
    back = settler.undo("robin")
    assert back["question"].startswith("Je change ceci : retrait : lampe Bureau › Applique")
    settler.apply(back["proposition"], "robin")
    assert "Applique" not in [lamp["name"] for lamp in room(domia, "office")["lights"]]


def test_a_situation_change_is_set_by_its_mode():
    settler = Settler(FakeDomia(), Memory(":memory:"))
    out = settler.propose(
        [{"op": "set", "kind": "situation_changes", "fields": {"departure.away_after_min": 20, "wake.mode": "OFF"}}],
        "robin",
    )
    assert "changements de situation : departure.away_after_min 10 → 20" in out["question"]
    assert "wake.mode PROPOSE → OFF" in out["question"]
    assert "rejeu" not in out


def test_the_mcp_needs_confirmed_to_apply():
    domia, memory = FakeDomia(), Memory(":memory:")
    proposal = Settler(domia, memory).propose([SHORTER], "robin")["proposition"]
    server = make_server(
        lambda: build(domia, None, memory, None, settings_write=True), Speaker(person="robin", client="mcp")
    )

    async def scenario():
        async with create_connected_server_and_client_session(server) as session:
            refused = (await session.call_tool("apply_settings", {"proposal": proposal})).content[0].text
            assert "confirmed" in refused and room(domia, "hallway")["vacant_after_sec"] != 120
            return (
                (await session.call_tool("apply_settings", {"proposal": proposal, "confirmed": True})).content[0].text
            )

    assert "appliqué" in asyncio.run(scenario()) and room(domia, "hallway")["vacant_after_sec"] == 120


def test_a_no_closes_the_proposal_even_after_a_while():
    # vu à l'orbe : « Non, ne l'applique pas » deux minutes après la question laissait la proposition en attente
    assistant, domia, memory = make([calls(call("propose_settings", {"changes": [SHORTER]}))])
    clock = [0.0]
    assistant.clock = lambda: clock[0]
    assistant.talk("éteins le couloir après 2 minutes", COMPTE)
    clock[0] += 120
    assert assistant.talk("Non, ne l'applique pas.", COMPTE)["answer"] == "D'accord, je ne fais rien."
    assert memory.settings_change(1)["state"] == "REFUSED" and "error" in Settler(domia, memory).apply(1, "robin")


def test_a_yes_to_a_setting_may_come_after_a_minute():
    assistant, domia, _ = make([calls(call("propose_settings", {"changes": [SHORTER]}))])
    clock = [0.0]
    assistant.clock = lambda: clock[0]
    assistant.talk("éteins le couloir après 2 minutes", COMPTE)
    clock[0] += 300
    assert (
        assistant.talk("oui", COMPTE)["answer"].startswith("C'est réglé")
        and room(domia, "hallway")["vacant_after_sec"] == 120
    )


def test_an_unchanged_field_is_not_a_change():
    draft = Draft(FakeDomia().config()["config"])
    same = room(FakeDomia(), "hallway")["vacant_after_sec"]
    try:
        draft.change({"op": "set", "kind": "room", "id": "hallway", "fields": {"vacant_after_sec": same}})
        raise AssertionError("rien ne change")
    except ValueError:
        pass
    draft.change({"op": "set", "kind": "room", "id": "hallway", "fields": {"vacant_after_sec": same, "name": "Entrée"}})
    assert len(draft.summary) == 1 and "name" in draft.summary[0]


def test_without_the_right_to_write_the_model_reads_settings_and_says_where_to_change_them():
    domia = FakeDomia()
    memory = Memory(":memory:")
    model = ScriptedModel([say("Le couloir s'éteint après 10 minutes ; ça se change dans Réglages.")])
    assistant = Assistant(domia, model, memory, lambda: build(domia, None, memory, None), clock=lambda: 0.0)
    assistant.talk("le couloir doit s'éteindre après 2 minutes", COMPTE)
    system, tools = model.requests[0][0][0]["content"], {t["function"]["name"] for t in model.requests[0][1]}
    assert "settings" in tools and not tools & {"propose_settings", "apply_settings", "undo_settings"}
    assert "se change dans Réglages" in system and "propose_settings" not in system
