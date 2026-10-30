"""La voie rapide (spec §5.1) : une table de phrases et des gestes qu'elles donnent, et les phrases qu'elle laisse au
modèle plutôt que de deviner."""

import pytest

from domia_assistant.grammar import Lexicon, is_no, is_yes, normalize, parse
from tests.house import HOUSE

LEX = Lexicon.of(HOUSE, {"la baie": ("cover", "living_cover"), "la tele": ("appliance", "tv_plug")})


def gestures(text, room=None):
    plan = parse(text, LEX, room)
    assert plan is not None, text
    return [(g.method, g.path, g.body) for g in plan.gestures]


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Allume la cuisine", [("POST", "/api/rooms/kitchen/commands", {"action": "TurnOnRoom"})]),
        ("éteins le salon", [("POST", "/api/rooms/living/commands", {"action": "TurnOffRoom"})]),
        ("Éteins le salon s'il te plaît", [("POST", "/api/rooms/living/commands", {"action": "TurnOffRoom"})]),
        (
            "allume la cuisine et la chambre",
            [
                ("POST", "/api/rooms/kitchen/commands", {"action": "TurnOnRoom"}),
                ("POST", "/api/rooms/bedroom/commands", {"action": "TurnOnRoom"}),
            ],
        ),
        ("allume le lampadaire", [("POST", "/api/lights/living_floor/commands", {"action": "TurnOn"})]),
        ("éteins le plafond du salon", [("POST", "/api/lights/living_ceiling/commands", {"action": "TurnOff"})]),
        (
            "salon à 30 %",
            [
                ("POST", "/api/lights/living_ceiling/commands", {"action": "SetBrightness", "brightness_pct": 30}),
                ("POST", "/api/lights/living_floor/commands", {"action": "SetBrightness", "brightness_pct": 30}),
            ],
        ),
        (
            "mets le chevet à 20%",
            [("POST", "/api/lights/bed_lamp/commands", {"action": "SetBrightness", "brightness_pct": 20})],
        ),
        (
            "met le chevet a20%",
            [("POST", "/api/lights/bed_lamp/commands", {"action": "SetBrightness", "brightness_pct": 20})],
        ),  # tapé vite
        (
            "volet du salon à 50",
            [("POST", "/api/covers/living_cover/commands", {"action": "SetPosition", "position": 50})],
        ),
        ("ferme la baie", [("POST", "/api/covers/living_cover/commands", {"action": "SetPosition", "position": 0})]),
        (
            "ouvre les volets du salon",
            [("POST", "/api/covers/living_cover/commands", {"action": "SetPosition", "position": 100})],
        ),
        (
            "chambre à 20 degrés",
            [("POST", "/api/emitters/bedroom_heat/commands", {"action": "SetSetpoint", "setpoint_c": 20.0})],
        ),
        (
            "mets le chauffage du salon à 21,5",
            [("POST", "/api/emitters/living_floor_heat/commands", {"action": "SetSetpoint", "setpoint_c": 21.5})],
        ),
        ("éteins la télé", [("POST", "/api/appliances/tv_plug/commands", {"action": "TurnOff"})]),
        ("mode nuit", [("PUT", "/api/situation", {"value": "NIGHT"})]),
        ("Bonne nuit", [("PUT", "/api/situation", {"value": "NIGHT"})]),
        ("je suis rentré", [("PUT", "/api/situation", {"value": "DAY"})]),
        ("garde le salon allumé", [("POST", "/api/rooms/living/commands", {"action": "KeepAsIs"})]),
        ("rends la main au salon", [("POST", "/api/rooms/living/commands", {"action": "Release"})]),
        (
            "lance le robot dans la cuisine",
            [("POST", "/api/machines/x40/commands", {"action": "StartCleaning", "room_ids": ["kitchen"]})],
        ),
        ("robot à la base", [("POST", "/api/machines/x40/commands", {"action": "ReturnToBase"})]),
        ("mets le robot en pause", [("POST", "/api/machines/x40/commands", {"action": "Pause"})]),
        # comme on parle : la politesse devant, le verbe à la fin ou à l'infinitif, les nombres en lettres
        ("tu peux éteindre dans la chambre ?", [("POST", "/api/rooms/bedroom/commands", {"action": "TurnOffRoom"})]),
        ("vas-y allume la cuisine", [("POST", "/api/rooms/kitchen/commands", {"action": "TurnOnRoom"})]),
        ("la cuisine, allume", [("POST", "/api/rooms/kitchen/commands", {"action": "TurnOnRoom"})]),
        (
            "volet du salon à quarante",
            [("POST", "/api/covers/living_cover/commands", {"action": "SetPosition", "position": 40})],
        ),
        (
            "mets la chambre à vingt et un degrés",
            [("POST", "/api/emitters/bedroom_heat/commands", {"action": "SetSetpoint", "setpoint_c": 21.0})],
        ),
        (
            "chevet soixante-dix pour cent",
            [("POST", "/api/lights/bed_lamp/commands", {"action": "SetBrightness", "brightness_pct": 70})],
        ),
        ("passe en nuit", [("PUT", "/api/situation", {"value": "NIGHT"})]),
        ("je suis rentré à la maison", [("PUT", "/api/situation", {"value": "DAY"})]),
        # deux demandes, et tout sauf une pièce
        (
            "allume la cuisine et éteins le salon",
            [
                ("POST", "/api/rooms/kitchen/commands", {"action": "TurnOnRoom"}),
                ("POST", "/api/rooms/living/commands", {"action": "TurnOffRoom"}),
            ],
        ),
        (
            "ferme la baie puis passe en nuit",
            [
                ("POST", "/api/covers/living_cover/commands", {"action": "SetPosition", "position": 0}),
                ("PUT", "/api/situation", {"value": "NIGHT"}),
            ],
        ),
        (
            "éteins tout sauf le salon",
            [
                ("POST", "/api/rooms/kitchen/commands", {"action": "TurnOffRoom"}),
                ("POST", "/api/rooms/bedroom/commands", {"action": "TurnOffRoom"}),
            ],
        ),
        (
            "coupe tout à part la cuisine et la chambre",
            [("POST", "/api/rooms/living/commands", {"action": "TurnOffRoom"})],
        ),
    ],
)
def test_a_sentence_becomes_existing_gestures(text, expected):
    assert gestures(text) == expected


def test_never_a_toggle():
    for text in ("allume le salon", "éteins la télé", "allume le lampadaire"):
        assert all(g[2]["action"] != "Toggle" for g in gestures(text) if g[2] and "action" in g[2])


def test_here_needs_the_room():
    assert parse("allume ici", LEX) is None
    assert gestures("allume ici", room="bedroom") == [("POST", "/api/rooms/bedroom/commands", {"action": "TurnOnRoom"})]


def test_the_whole_house_asks_first():
    plan = parse("éteins tout", LEX)
    assert plan.confirm == "J'éteins les 3 pièces ?"
    assert len(plan.gestures) == 3
    assert parse("on part", LEX).confirm == "Je passe la maison en Absent ?"
    assert parse("allume le salon", LEX).confirm is None
    assert parse("éteins tout et passe en nuit", LEX).confirm == "J'éteins les 3 pièces ?"


@pytest.mark.parametrize(
    "text",
    [
        "il fait sombre ici",  # pas de verbe connu
        "allume le salon doucement",  # un mot de trop
        "éteins le plafond",  # deux plafonds, sans pièce pour trancher
        "allume le garage",  # pas de garage
        "cuisine à 50 %",  # le plafond de la cuisine ne varie pas
        "salon à 150 %",
        "lance le robot",  # quel programme ?
        "prépare l'appart pour un film",
        "chambre à 20 % degrés",
        "allume les deux lampes",  # « deux » n'est pas une valeur
        "allume tout sauf le garage",
        "éteins le salon et dis-moi la température",  # la lecture : le modèle
        "allume la cuisine éteins le salon",  # deux verbes sans « et »
        "nuit",
        "",
    ],
)
def test_an_ambiguous_or_unknown_sentence_goes_to_the_model(text):
    assert parse(text, LEX) is None


def test_answers_are_short():
    assert parse("salon à 30 %", LEX).answer == "Salon à 30 %."
    assert parse("chambre à 20,5 degrés", LEX).answer == "Chambre à 20,5 °C."
    assert parse("allume le salon", LEX).answer == "C'est fait."


def test_a_synonym_resolves_one_object():
    assert LEX.resolve("la baie").id == "living_cover"
    assert LEX.resolve("le volet du salon") is None or LEX.resolve("le volet du salon").id == "living_cover"
    assert LEX.resolve("le plafond") is None


def test_yes_and_no():
    assert is_yes("Oui") and is_yes("oui vas-y") and is_yes("OK")
    assert is_no("non") and is_no("Pas maintenant")
    assert not is_yes("non")


def test_normalize():
    assert normalize("Éteins l’entrée à 20,5°") == "eteins l entree a 20.5 degres"
