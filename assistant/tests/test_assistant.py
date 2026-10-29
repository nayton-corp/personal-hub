"""La conversation contre un faux Domia et un modèle scripté (spec §17) : la voie rapide n'appelle pas le modèle ; le
modèle choisit ses outils et leurs arguments ; un geste qui touche toute la maison attend un « oui »."""

from domia_assistant.assistant import Assistant
from domia_assistant.llm import ScriptedModel, call, calls, say
from domia_assistant.memory import Memory
from domia_assistant.tools import Speaker, build
from tests.fakes import FakeDomia

COMPTE = Speaker(person="robin", client="client_phone")


def make(replies=(), domia=None):
    domia = domia or FakeDomia()
    memory = Memory(":memory:")
    model = ScriptedModel(list(replies))
    clock = [0.0]
    assistant = Assistant(domia, model, memory, lambda: build(domia, None, memory, None), clock=lambda: clock[0])
    return assistant, domia, model, memory, clock


def test_the_fast_path_never_reaches_the_model():
    assistant, domia, model, _, _ = make()
    answer = assistant.talk("éteins le salon", COMPTE)
    assert answer["answer"] == "C'est fait."
    assert answer["done"] == ["Salon"]
    assert domia.gestures == [("POST", "/api/rooms/living/commands", {"action": "TurnOffRoom"}, "robin")]
    assert model.requests == []


def test_the_whole_house_waits_for_a_yes_from_the_same_speaker():
    assistant, domia, _, _, _clock = make()
    asked = assistant.talk("on part", COMPTE)
    assert asked["answer"] == "Je passe la maison en Absent ?"
    assert asked["confirm"]
    assert domia.gestures == []
    # un autre appareil qui dit oui ne joue rien
    assistant.talk("oui", Speaker(person="kim", client="client_kim"))
    assert domia.gestures == []
    assert assistant.talk("oui", COMPTE)["answer"] == "Mode Absent."
    assert domia.gestures == [("PUT", "/api/situation", {"value": "AWAY"}, "robin")]


def test_no_or_too_late_plays_nothing():
    assistant, domia, _, _, clock = make([say("Rien à faire.")])
    assistant.talk("éteins tout", COMPTE)
    assert assistant.talk("non", COMPTE)["answer"] == "D'accord, je ne fais rien."
    assistant.talk("éteins tout", COMPTE)
    clock[0] += 61
    assistant.talk("oui", COMPTE)
    assert domia.gestures == []


def test_the_model_picks_its_tools_and_acts_on_behalf_of_the_speaker():
    assistant, domia, model, _, _ = make(
        [
            calls(call("house", {}, "c1")),
            calls(
                call("light_command", {"id": "living_floor", "action": "SetBrightness", "brightness_pct": 25}, "c2"),
                call("cover_command", {"id": "living_cover", "action": "SetPosition", "position": 0}, "c3"),
            ),
            say("Bon film !"),
        ]
    )
    answer = assistant.talk("prépare le salon pour un film", COMPTE)
    assert (
        answer["answer"] == "Fait : Salon › Lampadaire à 25 % ; Salon › Volet à 0 %. Bon film !"
    )  # les gestes d'après ce qui a été joué
    assert domia.gestures == [
        ("POST", "/api/lights/living_floor/commands", {"action": "SetBrightness", "brightness_pct": 25}, "robin"),
        ("POST", "/api/covers/living_cover/commands", {"action": "SetPosition", "position": 0}, "robin"),
    ]
    assert len(answer["done"]) == 2
    # le modèle a reçu qui parle, et ses outils de gestes générés du catalogue, sans Toggle
    messages, tools = model.requests[0]
    assert "Qui parle : Robin" in messages[1]["content"] and messages[1]["content"].endswith(
        "Demande : prépare le salon pour un film"
    )
    names = {t["function"]["name"] for t in tools}
    assert {"light_command", "room_command", "set_situation", "house", "remember"} <= names
    light = next(t for t in tools if t["function"]["name"] == "light_command")["function"]["parameters"]
    assert "Toggle" not in light["properties"]["action"]["enum"]
    assert light["properties"]["id"]["enum"] == ["living_ceiling", "living_floor", "kitchen_ceiling", "bed_lamp"]
    room = next(t for t in tools if t["function"]["name"] == "room_command")["function"]["description"]
    assert "Release() = rendre à l'automatique" in room and "KeepAsIs" not in room  # garder : voie rapide et écrans
    assert "until" not in light["properties"]
    # le résultat de house est rendu au modèle, en court
    assert '"situation": "DAY"' in model.requests[1][0][-1]["content"]


def test_a_house_wide_gesture_from_the_model_also_waits_for_yes():
    assistant, domia, _, _, _ = make([calls(call("set_situation", {"value": "AWAY"})), say("Bon voyage.")])
    asked = assistant.talk("on s'absente pour le week-end, tu t'occupes de la maison ?", COMPTE)
    assert asked["answer"] == "Je passe la maison en Absent ?"
    assert domia.gestures == []
    assistant.talk("oui", COMPTE)
    assert domia.gestures == [("PUT", "/api/situation", {"value": "AWAY"}, "robin")]


def test_a_refused_gesture_is_said_not_hidden():
    domia = FakeDomia(refuse={"/api/rooms/living/commands": "HA_UNAVAILABLE"})
    assistant, _, _, _, _ = make(domia=domia)
    assert assistant.talk("allume le salon", COMPTE)["answer"].startswith("Je n'ai pas pu")


def test_a_synonym_is_learned_then_used_by_the_fast_path():
    assistant, domia, model, _memory, _ = make()
    assert assistant.talk("La baie, c'est le volet du salon", COMPTE)["answer"] == "Noté : La baie, c'est Volet."
    assistant.talk("ferme la baie", COMPTE)
    assert domia.gestures == [
        ("POST", "/api/covers/living_cover/commands", {"action": "SetPosition", "position": 0}, "robin")
    ]
    assert model.requests == []


def test_a_room_voice_cannot_read_personal_notes():
    _assistant, _, _, memory, _ = make()
    memory.remember("Robin aime le salon à 22 degrés le soir", "robin", personal=True)
    memory.remember("Les ampoules E14 sont dans le placard de l'entrée", "robin")
    tools = build(FakeDomia(), None, memory, None)
    room_voice = Speaker(room="living")
    assert [n["text"] for n in tools.run("recall", {"question": "salon ampoules"}, room_voice)] == [
        "Les ampoules E14 sont dans le placard de l'entrée"
    ]
    assert len(tools.run("recall", {"question": "salon ampoules"}, COMPTE)) == 2
    assert tools.run("remember", {"fact": "x", "personal": True}, room_voice) == {
        "error": "une note personnelle a besoin de savoir qui parle"
    }


def test_the_model_down_is_said():
    assistant, _, _, _, _ = make([])
    assert assistant.talk("raconte-moi la maison", COMPTE)["answer"].startswith("Je ne peux pas réfléchir")


def test_the_model_sees_the_house_inventory_and_the_situation_in_french():
    assistant, _, model, _, _ = make([say("Il n'y a pas de chauffage au bureau.")])
    assistant.talk("il fait froid au bureau", COMPTE)
    system, asked = (m["content"] for m in model.requests[0][0][:2])
    assert (
        "Situation : Jour." in asked and "Situation" not in system
    )  # le moment va avec la demande : le système ne bouge pas
    assert "Maintenant" not in system
    assert "- Salon [living] : lampes Plafond [living_ceiling], Lampadaire [living_floor]" in system
    assert "chauffage/clim Sol de la chambre [bedroom_heat]" in system
    assert "- robot X40 [x40]" in system
    assert "même si l'appareil n'est pas dans la liste" in system  # la bibliothèque couvre plus que les objets pilotés


def test_the_system_prompt_is_the_same_from_one_sentence_to_the_next():
    # le serveur de modèle garde le calcul d'un préfixe identique : 40 s par question sans, quelques-unes avec
    assistant, _, model, _, clock = make([say("Rien de spécial."), say("Toujours rien.")])
    assistant.talk("quoi de neuf ?", COMPTE)
    clock[0] += 120
    assistant.talk("et maintenant ?", COMPTE)
    first, second = model.requests[0][0], model.requests[1][0]
    assert first[0] == second[0]
    assert first[1] != second[1]  # derniers échanges


def test_a_room_temperature_is_read_without_the_model():
    assistant, domia, model, _, _ = make()
    assert assistant.talk("quelle température au salon ?", COMPTE)["answer"] == "Salon : 21,4 °C."
    assert (
        assistant.talk("quelle est la température dans la cuisine", COMPTE)["answer"]
        == "Cuisine : pas de température connue."
    )
    assert model.requests == [] and domia.gestures == []


def test_turn_on_with_a_brightness_becomes_set_brightness():
    # c3 au banc : « une lumière douce dans la chambre » → TurnOn avec brightness_pct, que TurnOn ne porte pas
    domia = FakeDomia()
    tools = build(domia, None, Memory(":memory:"), None)
    tools.run("light_command", {"id": "bed_lamp", "action": "TurnOn", "brightness_pct": 30}, COMPTE)
    tools.run("light_command", {"id": "bed_lamp", "action": "TurnOn"}, COMPTE)
    assert [g[2] for g in domia.gestures] == [{"action": "SetBrightness", "brightness_pct": 30}, {"action": "TurnOn"}]


def test_what_is_on_is_read_without_the_model():
    assistant, domia, model, _, _ = make()
    assert assistant.talk("Qu'est-ce qui est allumé ?", COMPTE)["answer"] == "Allumé : Salon (Plafond, Meuble TV)."
    assert model.requests == [] and domia.gestures == []


def test_a_gesture_is_told_by_the_assistant_and_the_model_adds_what_was_read():
    # « éteins le salon et dis-moi la température » : le geste se dit d'après ce qui a été joué, la lecture par le modèle
    assistant, domia, model, _, _ = make(
        [
            calls(
                call("light_command", {"id": "living_floor", "action": "TurnOff"}), call("house", {"room": "living"})
            ),
            say("Il fait 21 °C au salon."),
        ]
    )
    answer = assistant.talk("éteins le lampadaire et dis-moi la température", COMPTE)
    assert answer["answer"] == "Fait : Salon › Lampadaire éteint. Il fait 21 °C au salon." and len(domia.gestures) == 1
    assert "déjà dit à la personne" in model.requests[1][0][-2]["content"]  # le modèle sait qu'il n'a pas à le redire


def test_a_failed_gesture_is_told_as_not_done():
    assistant, _domia, _, _, _ = make(
        [calls(call("light_command", {"id": "nope", "action": "TurnOff"})), say("J'ai éteint la lampe.")],
        FakeDomia(refuse={"/api/lights/nope/commands": "NOT_FOUND"}),
    )
    assert assistant.talk("éteins la lampe", COMPTE)["answer"].startswith("Pas fait : nope éteint")


def test_a_call_repeated_word_for_word_is_played_once():
    # mesuré : « ajoute du lait » appelait add_reminder deux fois de suite
    assistant, domia, model, _, _ = make(
        [
            calls(call("light_command", {"id": "living_floor", "action": "TurnOff"}, "c1")),
            calls(call("light_command", {"id": "living_floor", "action": "TurnOff"}, "c2")),
            say("Lampadaire éteint."),
        ]
    )
    assert len(assistant.talk("éteins juste le lampadaire, pas le reste", COMPTE)["done"]) == 1
    assert len(domia.gestures) == 1
    assert "déjà fait" in model.requests[2][0][-1]["content"]


def test_bedtime_comes_from_the_situations_in_a_few_lines():
    tools = build(FakeDomia(), None, Memory(":memory:"), None)
    lines = tools.run("situations", {"days": 2}, COMPTE)
    assert lines == ["samedi 24.10 23:41 Jour → Nuit (UI)", "dimanche 25.10 06:58 Nuit → Jour (AUTOMATION)"]


def test_in_two_steps_the_model_sees_only_the_tools_of_the_kind_of_request():
    # le modèle en deux temps (spec §16.12) : au banc, plus il voyait d'outils, plus il se trompait de geste
    domia = FakeDomia()
    model = ScriptedModel(
        [
            say("gestes, maison"),
            calls(call("light_command", {"id": "living_floor", "action": "TurnOff"})),
            say("Il fait 21 °C."),
        ]
    )
    assistant = Assistant(
        domia,
        model,
        Memory(":memory:"),
        lambda: build(domia, None, Memory(":memory:"), None),
        clock=lambda: 0.0,
        route=True,
    )
    answer = assistant.talk("éteins le lampadaire et dis-moi la température", COMPTE)
    assert answer["answer"] == "Fait : Salon › Lampadaire éteint. Il fait 21 °C."
    router, first = model.requests[0], model.requests[1]
    assert router[1] == [] and router[0][-1]["content"].endswith("éteins le lampadaire et dis-moi la température")
    shown = {t["function"]["name"] for t in first[1]}
    assert {"light_command", "house", "why"} <= shown and not shown & {
        "propose_settings",
        "search_library",
        "add_reminder",
    }


def test_an_unclear_kind_shows_every_tool():
    domia = FakeDomia()
    model = ScriptedModel([say("je ne sais pas"), say("Bonjour.")])
    assistant = Assistant(
        domia,
        model,
        Memory(":memory:"),
        lambda: build(domia, None, Memory(":memory:"), None),
        clock=lambda: 0.0,
        route=True,
    )
    assistant.talk("raconte-moi une blague", COMPTE)
    assert len(model.requests[1][1]) == len(build(domia, None, Memory(":memory:"), None).schemas())
