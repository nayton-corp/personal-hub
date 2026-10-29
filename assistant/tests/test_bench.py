"""Les cas du banc : bien formés, 56, chacun dit de plusieurs façons (variants.yaml), dans les familles de la spec (§13) ; et les gestes simples pris par la voie
rapide sur la maison de l'essai (seeds/seed-local.yaml), sans modèle."""

from collections import Counter
from pathlib import Path

import yaml

from domia_assistant.grammar import Lexicon, parse, read

ROOT = Path(__file__).resolve().parents[1]
CASES = yaml.safe_load((ROOT / "bench/cases.yaml").read_text(encoding="utf-8"))


def essai_house() -> dict:
    seed = yaml.safe_load((ROOT / "domia_assistant/contract/seed-local.yaml").read_text(encoding="utf-8"))
    rooms, machines = [], []
    for r in seed["rooms"]:
        rooms.append(
            {
                "id": r["id"],
                "name": r["name"],
                "lights": r.get("lights", []),
                "appliances": r.get("appliances", []) or [],
                "covers": r.get("covers", []) or [],
                "emitters": r.get("emitters", []) or [],
            }
        )
        machines += [{"id": m["id"], "name": m["name"], "room": r["id"]} for m in r.get("machines", []) or []]
    return {"rooms": rooms, "machines": machines}


def test_the_cases_in_the_families_of_the_spec():
    families = Counter(c["family"] for c in CASES["cases"])
    assert families == {
        "fast": 10,
        "compose": 13,
        "histoire": 8,
        "lecture": 5,
        "reglage": 8,
        "depannage": 6,
        "piege": 6,
    }
    assert len({c["id"] for c in CASES["cases"]}) == 56


def test_every_case_is_said_several_ways_with_control_sentences_apart():
    # Client 0 (2026-10-25) : des phrases variées, et des phrases de contrôle jamais regardées pour corriger
    import sys

    sys.path.insert(0, str(ROOT / "bench"))
    from run import expand

    variants = yaml.safe_load((ROOT / "bench/variants.yaml").read_text(encoding="utf-8"))
    ids = {c["id"] for c in CASES["cases"]}
    assert set(variants) <= ids
    said = [c for c in expand(CASES, variants, "all")]
    assert len(said) >= 3 * len(ids) and len({c["text"] for c in said}) == len(said)  # aucune phrase en double
    dev, control = expand(CASES, variants, "dev"), expand(CASES, variants, "control")
    assert {c["text"] for c in dev}.isdisjoint(c["text"] for c in control)
    variant = next(c for c in said if c["id"] == "f1.v1")
    assert variant["intent"] == "f1" and "fast" not in variant and variant["gestures"] == CASES["cases"][0]["gestures"]


def test_the_simple_gestures_take_the_fast_path_on_the_essai_house():
    lex = Lexicon.of(essai_house())
    for case in CASES["cases"]:
        plan = parse(case["text"], lex)
        if case.get("fast") and not case.get("gestures"):
            assert read(case["text"], lex, essai_house()) is not None, case["text"]  # une lecture, sans geste
        elif case.get("fast"):
            assert plan is not None, case["text"]
            got = [(g.method, g.path, g.body) for g in plan.gestures]
            for e in case["gestures"]:
                assert any(
                    p == e["path"] and all(b.get(k) == v for k, v in (e.get("body") or {}).items()) for _, p, b in got
                ), (case["id"], got)
        if case["family"] == "piege" and plan is not None:
            assert plan.confirm, case["text"]  # une phrase piège ne passe jamais sans question


def test_a_case_whose_object_is_absent_from_the_essai_is_skipped_and_allowed_gestures_are_not_grave():
    import sys

    sys.path.insert(0, str(ROOT / "bench"))
    from run import judge, missing

    house = essai_house()
    assert all(not missing(c, house) for c in CASES["cases"])  # la maison de démonstration a tout
    house["rooms"] = [dict(r, emitters=[]) for r in house["rooms"]]
    assert missing({"gestures": [{"path": "/api/emitters/bedroom_thermostat/commands"}]}, house) == [
        "bedroom_thermostat"
    ]
    c1 = next(c for c in CASES["cases"] if c["id"] == "c1")
    tv = ("POST", "/api/appliances/living_av/commands", {"action": "TurnOn"})
    ok, _why, grave = judge(c1, [tv], [], 1, "")
    assert grave == 0 and not ok  # toléré, mais les gestes attendus manquent


def test_one_of_accepts_either_right_gesture_and_still_requires_one():
    import sys

    sys.path.insert(0, str(ROOT / "bench"))
    from run import judge

    c2 = next(c for c in CASES["cases"] if c["id"] == "c2")
    room = ("POST", "/api/rooms/office/commands", {"action": "TurnOnRoom"})
    lamp = ("POST", "/api/lights/office_lamp/commands", {"action": "TurnOn"})
    assert judge(c2, [room], [], 1, "")[:1] == (True,)
    assert judge(c2, [lamp], [], 1, "")[:1] == (True,)
    ok, why, grave = judge(c2, [], [], 1, "")
    assert not ok and grave == 0 and why[0].startswith("geste manquant : un de")


def test_a_tool_that_answered_an_error_is_not_a_success():
    # mesuré : r3 et r4 comptés réussis alors que propose_settings rendait « route inconnue »
    from run import judge

    r3 = next(c for c in CASES["cases"] if c["id"] == "r3")
    assert judge(r3, [], ["propose_settings"], 1, "", set())[1] == ["outil en erreur : propose_settings"]
    assert judge(r3, [], ["propose_settings"], 1, "", {"propose_settings"})[0]


def test_without_the_right_to_write_a_setting_case_asks_only_where_to_change_it():
    import sys

    sys.path.insert(0, str(ROOT / "bench"))
    from run import read_only

    case = read_only({"id": "r1", "family": "reglage", "text": "…", "tools": ["propose_settings"], "none": True})
    assert "tools" not in case and case["none"] and case["words"] == ["reglages"]
