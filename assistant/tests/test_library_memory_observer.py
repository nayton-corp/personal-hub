"""La bibliothèque (fiches, passages cités, entretien dû), la mémoire (refus qui doublent le silence) et l'observateur
(au plus une remarque, jamais la nuit ni pendant la TV)."""

from datetime import UTC, date, datetime, timedelta

import pytest

from domia_assistant.library import Library, chunk, every
from domia_assistant.memory import Memory
from domia_assistant.observer import Observer, phrase
from tests.fakes import FakeDomia

T = datetime(2026, 10, 24, 18, 0, tzinfo=UTC)


@pytest.fixture
def library(tmp_path):
    folder = tmp_path / "Bibliothèque"
    lib = Library(folder, ":memory:")
    (folder / "lave-vaisselle").mkdir()
    (folder / "lave-vaisselle" / "manuel.md").write_text(
        "Codes d'erreur\n\nE24 : l'eau ne s'évacue pas. Nettoyer le filtre et vérifier le tuyau d'évacuation.\n\n"
        "E15 : fuite détectée dans le socle. Couper l'eau.",
        encoding="utf-8",
    )
    (folder / "bail.txt").write_text("Le loyer est payable d'avance le premier du mois.", encoding="utf-8")
    lib.save_card(
        "lave-vaisselle",
        {
            "name": "Lave-vaisselle",
            "room": "Cuisine",
            "brand": "V-Zug",
            "maintenance": [{"what": "nettoyer le filtre", "every": "1 mois", "last": "2026-09-01"}],
        },
    )
    return lib


def test_a_passage_comes_back_with_its_source(library):
    assert library.index() == 2  # le manuel tient en un passage, le bail aussi
    found = library.search("le lave-vaisselle affiche E24")
    assert found[0].source == "lave-vaisselle/manuel.md"
    assert "E24" in found[0].text
    assert library.index() == 0  # rien n'a changé : rien à réindexer


def test_embeddings_are_used_when_the_model_serves_them(tmp_path):
    vectors = {"chat": [1.0, 0.0], "chien": [0.0, 1.0]}
    lib = Library(
        tmp_path / "B", ":memory:", embed=lambda texts: [vectors["chat" if "chat" in t else "chien"] for t in texts]
    )
    (tmp_path / "B" / "a.txt").write_text("le chat dort", encoding="utf-8")
    (tmp_path / "B" / "b.txt").write_text("le chien court", encoding="utf-8")
    lib.index()
    assert lib.search("un chat ?")[0].source == "a.txt"


def test_an_error_code_beats_a_passage_that_only_sounds_alike(tmp_path):
    # mesuré sur la vraie maison : « E24 » ramenait une page de la notice qui parle de pompe, pas la ligne du code
    lib = Library(
        tmp_path / "B",
        ":memory:",
        embed=lambda texts: [[1.0, 0.0] if "pompe" in t or "affiche" in t else [0.6, 0.8] for t in texts],
    )
    (tmp_path / "B" / "notice.txt").write_text("Nettoyer la pompe de vidange et les filtres.", encoding="utf-8")
    (tmp_path / "B" / "codes.md").write_text("E:24 (E24) : l'eau ne se vidange pas.", encoding="utf-8")
    lib.index()
    assert lib.search("le lave-vaisselle affiche E24")[0].source == "codes.md"
    assert lib.search("le lave-vaisselle affiche quoi")[0].source == "notice.txt"  # sans code, le sens seul


def test_cards_and_maintenance(library):
    assert library.card("lave-vaisselle")["brand"] == "V-Zug"
    with pytest.raises(ValueError):
        library.save_card("lave-vaisselle", {"couleur": "blanc"})
    with pytest.raises(ValueError):
        library.save_card("../bail", {"name": "x"})
    assert library.maintenance_due(date(2026, 9, 30)) == []
    assert library.maintenance_due(date(2026, 10, 1))[0]["what"] == "nettoyer le filtre"
    assert (
        every("2 semaines") == timedelta(days=14) and every("1 an") == timedelta(days=365) and every("bientôt") is None
    )


def test_chunks_stay_short():
    parts = chunk("a" * 3000 + "\n\n" + "b" * 10, size=1200)
    assert all(len(p) <= 1200 for p in parts) and parts[-1].endswith("b")


def test_a_refusal_doubles_the_silence():
    memory = Memory(":memory:")
    assert memory.refuse("CLEANING_DUE:kitchen", T) == T + timedelta(days=7)
    assert memory.quiet("CLEANING_DUE:kitchen", T + timedelta(days=6))
    assert not memory.quiet("CLEANING_DUE:kitchen", T + timedelta(days=8))
    assert memory.refuse("CLEANING_DUE:kitchen", T) == T + timedelta(days=14)


def test_forget_only_your_own_or_the_household():
    memory = Memory(":memory:")
    mine = memory.remember("j'aime le thé", "kim", personal=True)
    assert not memory.forget(mine, "robin")
    assert memory.forget(mine, "kim")


CLEANING = {
    "id": "CLEANING_DUE:kitchen",
    "kind": "CLEANING_DUE",
    "subject": "kitchen",
    "subject_name": "Cuisine",
    "values": {"days": 9},
}
BATTERY = {
    "id": "BATTERY_LOW:hall_btn",
    "kind": "BATTERY_LOW",
    "subject": "hall_btn",
    "subject_name": "bouton de l'entrée",
    "values": {"battery_pct": 8.0},
}


def test_one_remark_at_a_time_the_most_urgent_first_and_not_again_today():
    domia = FakeDomia(observations=[CLEANING, BATTERY])
    observer = Observer(domia, Memory(":memory:"))
    assert observer.run_once(T).subject == "BATTERY_LOW:hall_btn"
    assert domia.notices == [("Pile", "La pile de bouton de l'entrée est à 8 %. À changer bientôt.")]
    assert observer.run_once(T + timedelta(hours=1)).subject == "CLEANING_DUE:kitchen"
    assert observer.run_once(T + timedelta(hours=2)) is None
    assert len(domia.notices) == 2


def test_silent_at_night_and_during_tv():
    night = FakeDomia(observations=[BATTERY])
    night._house["situation"]["value"] = "NIGHT"
    assert Observer(night, Memory(":memory:")).run_once(T) is None
    tv = FakeDomia(observations=[BATTERY])
    tv.facts = lambda: {"estimates": {"tv": {"kind": "WATCHING_TV", "fact": {"value": True}}}}
    assert Observer(tv, Memory(":memory:")).run_once(T) is None
    assert night.notices == [] and tv.notices == []


def test_phrases():
    assert (
        phrase(CLEANING).message == "Cuisine n'a pas été nettoyée depuis 9 jours. Je lance le robot quand vous sortez ?"
    )
    on = {
        "id": "APPLIANCE_ON_LONG:tv",
        "kind": "APPLIANCE_ON_LONG",
        "subject_name": "Meuble TV",
        "values": {"hours": 14, "standby": True, "power_w": 4.2},
    }
    assert phrase(on).message == "Meuble TV est allumé depuis 14 h, en veille (4 W). Je l'éteins ?"


def test_maintenance_joins_the_observations(library):
    domia = FakeDomia()
    observer = Observer(domia, Memory(":memory:"), library)
    remark = observer.run_once(datetime(2026, 10, 2, 9, 0, tzinfo=UTC))
    assert remark.kind == "MAINTENANCE_DUE"
    assert domia.notices[0][1].startswith("Lave-vaisselle : nettoyer le filtre")


def test_a_nameplate_photo_is_read_by_the_vision_model(library):
    from domia_assistant.tools import Speaker, library_tools

    (library.folder / "à-trier" / "plaque.jpg").write_bytes(b"\xff\xd8photo")
    seen = []
    tools = {
        t.name: t
        for t in library_tools(library, lambda image, mime, q: seen.append((image, mime)) or '{"brand": "V-Zug"}')
    }
    assert tools["inbox"].run({}, Speaker()) == ["plaque.jpg"]
    assert tools["read_photo"].run({"file": "plaque.jpg"}, Speaker())["read"] == '{"brand": "V-Zug"}'
    assert seen == [(b"\xff\xd8photo", "image/jpeg")]
    assert "error" in tools["read_photo"].run({"file": "../bail.txt"}, Speaker())
