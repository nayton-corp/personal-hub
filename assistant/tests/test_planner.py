"""Le plan de demain et ses engagements (spec « préparer demain » §5, §6) : une table de situations → lignes et
propositions ; un engagement joué, refusé par sa condition, expiré, annulé ; le « oui » qui suit le plan."""

import copy
from datetime import UTC, date, datetime, timedelta

from domia_assistant import planner
from domia_assistant.agenda import AgendaUnavailable
from domia_assistant.assistant import Assistant
from domia_assistant.engagements import Engagements
from domia_assistant.memory import Memory
from domia_assistant.observer import Observer
from domia_assistant.tools import Speaker, Toolbox
from tests.fakes import FakeDomia
from tests.house import HOUSE

ZONE = "Europe/Zurich"
TOMORROW = date(2026, 10, 27)  # un mardi, en heure d'hiver (UTC+1)
NOW = datetime(2026, 10, 26, 20, 0, tzinfo=UTC)  # 21 h à la maison

DUE = {
    "id": "CLEANING_DUE:kitchen",
    "kind": "CLEANING_DUE",
    "subject": "kitchen",
    "subject_name": "Cuisine",
    "values": {"days": 9},
}
WINDOW = {
    "id": "WINDOW_OPEN_RAIN:w1",
    "kind": "WINDOW_OPEN_RAIN",
    "subject": "w1",
    "subject_name": "Fenêtre de la chambre",
    "values": {"rain_from": "2026-10-27T02:00:00Z"},
}
PARENTS = {
    "title": "Chez les parents",
    "start": "2026-10-27T10:00:00+01:00",
    "end": "2026-10-27T18:00:00+01:00",
    "all_day": False,
    "location": "Lausanne",
}
DENTIST = {
    "title": "Dentiste",
    "start": "2026-10-27T08:00:00+01:00",
    "end": "2026-10-27T08:30:00+01:00",
    "all_day": False,
    "location": "Vevey",
}
RAINY = {
    "fetched_at": "2026-10-26T19:30:00Z",
    "stale": False,
    "rain_from": "2026-10-27T14:00:00Z",
    "tomorrow": {
        "date": "2026-10-27",
        "temperature_min_c": 7.6,
        "temperature_max_c": 12.2,
        "rain_from": "2026-10-27T14:00:00Z",
        "rain_mm": 6.1,
        "gust_max_kmh": 70.0,
        "hours": 24,
    },
}
TUESDAY_OUT = {
    "groups": {
        "tuesday": {
            "days": 4,
            "departure_days": 4,
            "departure_rate": 1.0,
            "departure": {"median": "07:55:00", "spread_min": 5, "days": 4},
        }
    }
}


class FakeAgenda:
    def __init__(self, events=None, reminders=None, broken=False):
        self.events = events or []
        self.open = reminders or []
        self.broken = broken

    def calendar(self, start, end):
        if self.broken:
            raise AgendaUnavailable("non autorisé")
        return list(self.events)

    def reminders(self, list_name=None):
        if self.broken:
            raise AgendaUnavailable("non autorisé")
        return list(self.open)


def make_plan(events=(), reminders=(), weather=None, habits=None, observations=(), house=None):
    return planner.plan(
        TOMORROW, ZONE, list(events), list(reminders), weather, habits, list(observations), house or HOUSE
    )


def test_an_absence_in_the_agenda_and_a_room_to_clean_propose_the_robot_during_it():
    p = make_plan(events=[DENTIST, PARENTS], weather=RAINY, observations=[DUE])
    assert p.lines[0] == "Demain : Dentiste à 8 h, Chez les parents 10 h–18 h."
    assert p.lines[1] == "Pluie dès 15 h, 8 à 12 °C, rafales à 70 km/h."
    robot = p.offers[0]
    assert robot.kind == planner.ROBOT_AWAY
    assert (
        robot.question
        == "Je lance le robot (Cuisine) pendant « Chez les parents » (10 h–18 h), quand la maison est vide ?"
    )
    assert robot.gesture["body"] == {"action": "StartCleaning", "room_ids": ["kitchen"]}
    assert robot.after_away_min == 15 and robot.condition["situation"] == "AWAY"
    assert "agenda : Chez les parents" in robot.because


def test_without_agenda_a_habitual_departure_is_enough_and_without_either_nothing_is_proposed():
    habit = make_plan(habits=TUESDAY_OUT, observations=[DUE]).offers[0]
    assert "après ton départ (d'habitude vers 7 h 55)" in habit.question
    assert make_plan(observations=[DUE]).offers == []
    # un rendez-vous sans lieu, ou trop court, n'est pas une absence
    assert make_plan(events=[{**PARENTS, "location": ""}], observations=[DUE]).offers == []
    assert make_plan(events=[DENTIST], observations=[DUE]).offers == []


def test_an_open_cover_is_closed_before_daytime_rain_but_never_at_night():
    close = make_plan(weather=RAINY).offers[0]
    assert close.kind == planner.CLOSE_BEFORE_RAIN
    assert close.question == "Je ferme Volet à 14 h 30, avant la pluie ?"
    assert close.at == datetime(2026, 10, 27, 13, 30, tzinfo=UTC)
    night = copy.deepcopy(RAINY)
    night["tomorrow"]["rain_from"] = "2026-10-27T02:00:00Z"
    assert make_plan(weather=night).offers == []
    closed = copy.deepcopy(HOUSE)
    closed["rooms"][0]["covers"][0]["position"] = 0
    assert make_plan(weather=RAINY, house=closed).offers == []


def test_a_stale_forecast_is_said_and_proposes_nothing():
    stale = {**RAINY, "stale": True}
    p = make_plan(weather=stale)
    assert p.lines == ["La prévision météo est trop vieille : je ne m'y fie pas."]
    assert p.offers == []
    assert make_plan(weather={"reason": "NO_SITE"}).lines == []


def test_a_reminder_for_tomorrow_comes_at_the_habitual_departure_and_at_most_two_offers_are_made():
    pharmacy = {"id": "r1", "title": "Pharmacie", "due": "2026-10-27"}
    p = make_plan(reminders=[pharmacy], weather=RAINY, habits=TUESDAY_OUT, observations=[DUE, WINDOW])
    assert [o.kind for o in p.offers] == [planner.ROBOT_AWAY, planner.CLOSE_BEFORE_RAIN]
    assert "À faire : Pharmacie." in p.lines
    assert "Fenêtre de la chambre est ouverte et la pluie arrive." in p.lines
    remind = make_plan(reminders=[pharmacy], habits=TUESDAY_OUT).offers[0]
    assert remind.kind == planner.REMIND_AT_DEPARTURE
    assert remind.at == datetime(2026, 10, 27, 6, 45, tzinfo=UTC)
    assert remind.notify["message"] == "N'oublie pas : Pharmacie."


def setup(house=None, weather=None, agenda=None):
    domia = FakeDomia(house=house, observations=[DUE], weather=weather or RAINY, habits=TUESDAY_OUT)
    memory = Memory(":memory:")
    engagements = Engagements(domia, memory, agenda, ZONE)
    return domia, memory, engagements


def test_the_brief_offers_and_a_yes_is_kept_fifteen_minutes_after_the_house_empties():
    domia, memory, engagements = setup()
    observer = Observer(domia, memory, None, FakeAgenda([PARENTS]), engagements, ZONE)
    message = observer.brief(NOW, TOMORROW)
    assert "Je lance le robot (Cuisine)" in message
    assert "Cuisine n'a pas été nettoyée" not in message  # le constat est dans la proposition
    assert len(engagements.waiting(NOW)) == 2

    accepted = engagements.accept(None, "robin", NOW + timedelta(minutes=5))
    assert len(accepted) == 2
    assert engagements.tick(NOW + timedelta(hours=1)) == []  # personne n'est parti

    leave = datetime(2026, 10, 27, 9, 30, tzinfo=UTC)
    domia._house["situation"] = {"value": "AWAY", "updated_at": leave.isoformat()}
    assert engagements.tick(leave + timedelta(minutes=10)) == []
    said = engagements.tick(leave + timedelta(minutes=15))
    assert said == ["C'est fait : j'ai lancé le robot (Cuisine), comme convenu."]
    assert domia.gestures[-1] == (
        "POST",
        "/api/machines/x40/commands",
        {"action": "StartCleaning", "room_ids": ["kitchen"]},
        "robin",
    )
    assert engagements.tick(leave + timedelta(minutes=16)) == []  # une fois


def test_a_condition_that_no_longer_holds_plays_nothing_and_says_so_once():
    domia, memory, engagements = setup()
    observer = Observer(domia, memory, None, FakeAgenda(), engagements, ZONE)
    observer.brief(NOW, TOMORROW)
    engagements.accept(None, "robin", NOW)
    domia._house["rooms"][0]["covers"][0]["position"] = 0  # fermé à la main dans la journée
    said = engagements.tick(datetime(2026, 10, 27, 13, 31, tzinfo=UTC))
    assert said == ["Je n'ai pas fermé Volet avant la pluie : il était déjà fermé."]
    assert not [g for g in domia.gestures if "covers" in g[1]]
    assert domia.notices[-1] == ("Prévu hier soir", said[0])


def test_an_engagement_expires_at_midnight_and_can_be_cancelled():
    domia, memory, engagements = setup(weather={"reason": "OFF"})
    Observer(domia, memory, None, FakeAgenda([PARENTS]), engagements, ZONE).brief(NOW, TOMORROW)
    [_robot] = engagements.accept(None, "robin", NOW)
    assert engagements.listing(NOW)[0]["state"] == "prévu"
    said = engagements.tick(datetime(2026, 10, 27, 23, 0, tzinfo=UTC))  # minuit passé, à la maison
    assert said == ["Je n'ai pas lancé le robot (Cuisine) : la maison n'a jamais été vide."]

    Observer(domia, memory, None, FakeAgenda([PARENTS]), engagements, ZONE).brief(NOW, TOMORROW)
    [again] = engagements.accept(None, "robin", NOW)
    assert engagements.cancel(again["id"])
    assert engagements.listing(NOW) == []


class Answers:
    def chat(self, messages, tools):
        assert "Propositions en attente d'un oui : [" in messages[1]["content"]
        return {"content": "Oui à quoi ?"}


class Silent:
    def chat(self, messages, tools):
        raise AssertionError("le oui du plan ne passe pas par le modèle")


def _soon():
    """Un lendemain à venir : les offres du brief expirent à sa fin, et ces tests parlent au présent."""
    tomorrow = (datetime.now(UTC) + timedelta(days=1)).date()
    return tomorrow, {**PARENTS, "start": f"{tomorrow}T10:00:00+01:00", "end": f"{tomorrow}T18:00:00+01:00"}


def test_the_first_yes_after_the_brief_accepts_and_a_later_yes_goes_to_the_model():
    domia, memory, engagements = setup(weather={"reason": "OFF"})
    tomorrow, parents = _soon()
    Observer(domia, memory, None, FakeAgenda([parents]), engagements, ZONE).brief(datetime.now(UTC), tomorrow)
    assistant = Assistant(domia, Silent(), memory, lambda: None, ZONE, engagements=engagements)
    answer = assistant.talk("oui", Speaker(person="robin", client="phone"))
    assert answer["answer"] == "C'est noté."
    assert engagements.memory.engagements("ACCEPTED")[0]["person"] == "robin"

    Observer(domia, memory, None, FakeAgenda([parents]), engagements, ZONE).brief(datetime.now(UTC), tomorrow)
    memory.log("robin", None, "tu veux que je cherche ?", "…", datetime.now(UTC) + timedelta(seconds=1))
    assistant.model = Answers()
    assistant.toolbox = lambda: Toolbox([])
    assert assistant.talk("oui", Speaker(person="robin", client="phone"))["answer"] == "Oui à quoi ?"
    assert len(engagements.waiting(datetime.now(UTC))) == 1


def test_no_after_the_brief_refuses_the_offers():
    domia, memory, engagements = setup(weather={"reason": "OFF"})
    tomorrow, parents = _soon()
    Observer(domia, memory, None, FakeAgenda([parents]), engagements, ZONE).brief(datetime.now(UTC), tomorrow)
    assistant = Assistant(domia, Silent(), memory, lambda: None, ZONE, engagements=engagements)
    assert assistant.talk("non", Speaker(person="robin"))["answer"] == "D'accord, je ne prévois rien."
    assert engagements.waiting(datetime.now(UTC)) == []
