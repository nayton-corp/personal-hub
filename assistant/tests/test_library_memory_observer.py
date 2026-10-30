"""La bibliothèque (fiches, passages cités, entretien dû), la mémoire (refus qui doublent le silence) et l'observateur
(au plus une remarque, jamais la nuit ni pendant la TV)."""

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pyrage
import pytest
from hub.core import tools
from hub.core.auth import Principal
from hub.core.context import HubContext
from hub.core.registry import Registry
from hub.domains.documents.domain import DocumentsDomain
from hub.domains.documents.model import chunk, every
from hub.platform.settings import Paths, Secrets, Settings

from domia_assistant.library import Library, LibraryUnavailable
from domia_assistant.memory import Memory
from domia_assistant.observer import Observer, phrase
from tests.fakes import FakeDomia

T = datetime(2026, 10, 24, 18, 0, tzinfo=UTC)
HOUSEHOLD = Principal("token:library", frozenset({"documents:household", "documents:propose"}))
CARD = """name: Lave-vaisselle
room: Cuisine
brand: V-Zug
maintenance:
  - {what: nettoyer le filtre, every: 1 mois, last: 2026-09-01}
"""


class HubApi:
    """`hub.brain.hubapi.HubApi`, branché sur un vrai hub en mémoire avec le jeton de la bibliothèque : ses outils, ses
    portées, ses erreurs (le type seulement), ses réponses passées par JSON."""

    def __init__(self, ctx: HubContext, principal: Principal = HOUSEHOLD):
        self.ctx, self.principal, self.up = ctx, principal, True

    def call(self, domain: str, name: str, args: dict) -> object:
        if not self.up:
            raise ConnectionError("hub éteint")
        return json.loads(json.dumps(tools.call(self.ctx, self.principal, domain, name, args)))


def hub_settings(root: Path) -> Settings:
    root.mkdir(parents=True)
    key = root / "age.key"
    key.write_text(f"{pyrage.x25519.Identity.generate()}\n")
    paths = Paths(data=root / "data", inbox=root / "inbox", archive=root / "archive", backup=root / "backup")
    return Settings(paths=paths, secrets=Secrets(file=root / "absent.enc.yaml", age_key_file=key))


@pytest.fixture
def hub(tmp_path):
    """Le hub, sa bibliothèque reprise de ~/Domia/Bibliothèque/ (la notice et la fiche « foyer », un bulletin privé)."""
    folder = tmp_path / "Bibliothèque"
    (folder / "lave-vaisselle").mkdir(parents=True)
    (folder / "lave-vaisselle" / "manuel.md").write_text(
        "Codes d'erreur\n\nE24 : l'eau ne s'évacue pas. Nettoyer le filtre et vérifier le tuyau d'évacuation.\n\n"
        "E15 : fuite détectée dans le socle. Couper l'eau.",
        encoding="utf-8",
    )
    (folder / "bail.txt").write_text("Le loyer est payable d'avance le premier du mois.", encoding="utf-8")
    (folder / "lave-vaisselle.yaml").write_text(CARD, encoding="utf-8")
    settings = hub_settings(tmp_path / "hub")
    documents = DocumentsDomain(settings)
    documents.today = lambda: date(2026, 10, 2)  # type: ignore[method-assign]
    ctx = HubContext.build(settings, Registry([documents]))
    ctx.migrate_all()
    documents.import_library(folder)
    inbox = settings.paths.inbox_of("documents")
    inbox.mkdir(parents=True)
    (inbox / "salaire.txt").write_text("Bulletin de salaire : le loyer est retenu.", encoding="utf-8")
    documents.process_inbox()  # privé : jamais lu par la bibliothèque du foyer
    yield ctx
    ctx.dispose()


@pytest.fixture
def library(hub, tmp_path):
    (tmp_path / "à-trier").mkdir()
    return Library(HubApi(hub), tmp_path / "à-trier")


def test_a_passage_comes_back_with_its_source(library):
    found = library.search("le lave-vaisselle affiche E24")
    assert found[0].cite() == "manuel"
    assert "E24" in found[0].text
    assert [p.cite() for p in library.search("loyer")] == ["bail"]  # le bulletin privé reste au hub
    assert library.search("E2") == []


def test_cards_and_maintenance_come_from_the_hub(library, hub):
    assert library.card("lave-vaisselle")["brand"] == "V-Zug"
    assert library.card("frigo") is None
    assert library.cards()["lave-vaisselle"]["name"] == "Lave-vaisselle"
    assert library.maintenance_due()[0]["what"] == "nettoyer le filtre"
    proposed = library.save_card("lave-vaisselle", {"serial": "S-1"})
    assert (proposed["status"], proposed["summary"]) == ("pending", "Fiche « Lave-vaisselle » : serial")
    assert "serial" not in library.card("lave-vaisselle")  # une carte dans l'app, pas une écriture
    with pytest.raises(LibraryUnavailable):
        library.save_card("lave-vaisselle", {"couleur": "blanc"})


def test_the_house_goes_on_without_the_hub(library):
    library.api.up = False
    with pytest.raises(LibraryUnavailable):
        library.search("E24")
    from domia_assistant.tools import Speaker, library_tools

    found = {t.name: t for t in library_tools(library)}["search_library"].run({"question": "E24"}, Speaker())
    assert found == {"error": "bibliothèque du hub : ConnectionError"}
    assert Observer(FakeDomia(), Memory(":memory:"), library).run_once(T) is None


def test_every_counts_weeks_and_years():
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

    (library.inbox_dir / "plaque.jpg").write_bytes(b"\xff\xd8photo")
    seen = []
    tools = {
        t.name: t
        for t in library_tools(library, lambda image, mime, q: seen.append((image, mime)) or '{"brand": "V-Zug"}')
    }
    assert tools["inbox"].run({}, Speaker()) == ["plaque.jpg"]
    assert tools["read_photo"].run({"file": "plaque.jpg"}, Speaker())["read"] == '{"brand": "V-Zug"}'
    assert seen == [(b"\xff\xd8photo", "image/jpeg")]
    assert "error" in tools["read_photo"].run({"file": "../bail.txt"}, Speaker())
