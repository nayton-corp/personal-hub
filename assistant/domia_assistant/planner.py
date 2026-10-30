"""Le plan de demain (spec « préparer demain » §5) : l'agenda, la météo, les habitudes et les constats de Domia
rassemblés en au plus quatre lignes, et au plus deux propositions. Sans modèle de langue : des règles fixes, testables.

Chaque proposition porte son geste et la condition revérifiée au moment de le jouer (`engagements.py`). Le plan ne parle
que de ce qui a une source, et la garde (`because`) pour répondre à « pourquoi ? »."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

ROBOT_AWAY = "ROBOT_AWAY"
CLOSE_BEFORE_RAIN = "CLOSE_BEFORE_RAIN"
REMIND_AT_DEPARTURE = "REMIND_AT_DEPARTURE"

LONG_ABSENCE = timedelta(hours=2)  # un événement avec un lieu, d'au moins 2 h : on est sorti
HABIT_RATE = 0.8  # un départ habituel : au moins 4 jours sur 5
AFTER_DEPARTURE_MIN = 15
BEFORE_RAIN = timedelta(minutes=30)
DAYTIME = (time(7, 0), time(22, 0))  # jamais la nuit
GUSTS_KMH = 60
MAX_LINES = 4
MAX_OFFERS = 2
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


@dataclass(frozen=True)
class Offer:
    """Une proposition : la question posée, ce qui sera joué, quand, et ce qui doit encore tenir à ce moment-là.

    `at` : une heure (UTC) ; `after_away_min` : tant de minutes après le passage en Absent. `gesture` : un geste de
    Domia {method, path, body, label} ; `notify` : un message {title, message} à la place d'un geste."""

    kind: str
    question: str
    what: str  # « lancé le robot » : pour dire « c'est fait » ou « je n'ai pas … »
    condition: dict
    because: list[str]
    gesture: dict | None = None
    notify: dict | None = None
    at: datetime | None = None
    after_away_min: int | None = None


@dataclass
class Plan:
    lines: list[str] = field(default_factory=list)
    offers: list[Offer] = field(default_factory=list)

    def message(self) -> str:
        return " ".join(self.lines + [o.question for o in self.offers])


def hm(t: datetime | time) -> str:
    return f"{t.hour} h" if t.minute == 0 else f"{t.hour} h {t.minute:02d}"


def _dt(raw: str | None, tz: ZoneInfo) -> datetime | None:
    if not raw:
        return None
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (value if value.tzinfo else value.replace(tzinfo=tz)).astimezone(tz)


def absences(events: list[dict], tz: ZoneInfo) -> list[tuple[str, datetime | None, datetime | None]]:
    """Les sorties de demain dans l'agenda : un événement avec un lieu, toute la journée ou d'au moins 2 h."""
    out: list[tuple[str, datetime | None, datetime | None]] = []
    for e in events:
        if not (e.get("location") or "").strip():
            continue
        if e.get("all_day"):
            out.append((e.get("title") or "sorti", None, None))
            continue
        start, end = _dt(e.get("start"), tz), _dt(e.get("end"), tz)
        if start and end and end - start >= LONG_ABSENCE:
            out.append((e.get("title") or "sorti", start, end))
    return out


def habit(habits: dict | None, day: date) -> dict:
    return ((habits or {}).get("groups") or {}).get(WEEKDAYS[day.weekday()]) or {}


def habitual_departure(habits: dict | None, day: date, tz: ZoneInfo) -> datetime | None:
    """L'heure du départ habituel de ce jour de la semaine, s'il part au moins 4 jours sur 5."""
    group = habit(habits, day)
    departure = (group.get("departure") or {}).get("median")
    if not departure or (group.get("departure_rate") or 0) < HABIT_RATE:
        return None
    return datetime.combine(day, time.fromisoformat(departure), tz)


def plan(
    tomorrow: date,
    zone: str,
    events: list[dict],
    reminders: list[dict],
    weather: dict | None,
    habits: dict | None,
    observations: list[dict],
    house: dict,
) -> Plan:
    tz = ZoneInfo(zone)
    out = Plan()
    agenda = _agenda_line(events, tz)
    if agenda:
        out.lines.append(agenda)
    forecast, rain_from = _weather_line(weather, tz)
    if forecast:
        out.lines.append(forecast)
    due = [r for r in reminders if (r.get("due") or "")[:10] and r["due"][:10] <= tomorrow.isoformat()]
    if due:
        out.lines.append("À faire : " + ", ".join(r.get("title") or "?" for r in due[:4]) + ".")
    for o in observations:
        if o.get("kind") == "WINDOW_OPEN_RAIN":
            out.lines.append(f"{o.get('subject_name')} est ouverte et la pluie arrive.")

    out.offers = [
        o
        for o in (
            _robot(tomorrow, tz, events, habits, observations, house),
            _close(rain_from, tz, house),
            _remind(tomorrow, tz, due, habits),
        )
        if o is not None
    ][:MAX_OFFERS]
    out.lines = out.lines[:MAX_LINES]
    return out


def _agenda_line(events: list[dict], tz: ZoneInfo) -> str | None:
    parts = []
    for e in events[:3]:
        start, end = _dt(e.get("start"), tz), _dt(e.get("end"), tz)
        if e.get("all_day") or not start:
            parts.append(e.get("title") or "?")
        elif end and end - start >= LONG_ABSENCE:
            parts.append(f"{e.get('title')} {hm(start)}–{hm(end)}")
        else:
            parts.append(f"{e.get('title')} à {hm(start)}")
    return "Demain : " + ", ".join(parts) + "." if parts else None


def _weather_line(weather: dict | None, tz: ZoneInfo) -> tuple[str | None, datetime | None]:
    """La météo de demain en une phrase, et la première heure de pluie ; rien d'une prévision vieille ou absente."""
    if not weather or weather.get("reason"):
        return None, None
    if weather.get("stale"):
        return "La prévision météo est trop vieille : je ne m'y fie pas.", None
    day = weather.get("tomorrow") or {}
    rain_from = _dt(day.get("rain_from"), tz)
    words = [f"Pluie dès {hm(rain_from)}" if rain_from else "Sec"]
    low, high = day.get("temperature_min_c"), day.get("temperature_max_c")
    if low is not None and high is not None:
        words.append(f"{round(low)} à {round(high)} °C")
    if (day.get("gust_max_kmh") or 0) >= GUSTS_KMH:
        words.append(f"rafales à {round(day['gust_max_kmh'])} km/h")
    return ", ".join(words) + ".", rain_from


def _robot(
    tomorrow: date, tz: ZoneInfo, events: list[dict], habits: dict | None, observations: list[dict], house: dict
) -> Offer | None:
    """Une pièce à nettoyer et une absence demain (agenda ou habitude) : le robot 15 min après le départ."""
    due = [o for o in observations if o.get("kind") == "CLEANING_DUE"]
    if not due:
        return None
    rooms = [o["subject"] for o in due]
    robot = next((m for m in house.get("machines", []) or [] if set(rooms) & set(m.get("cleanable_rooms") or [])), None)
    if robot is None:
        return None
    rooms = [r for r in rooms if r in (robot.get("cleanable_rooms") or [])]
    due = [o for o in due if o["subject"] in rooms]
    names = [o.get("subject_name") or o["subject"] for o in due]
    out = absences(events, tz)
    if out:
        title, start, end = out[0]
        when = f"pendant « {title} »" + (f" ({hm(start)}–{hm(end)})" if start and end else "")
        because = [f"agenda : {title}"]
    else:
        departure = habitual_departure(habits, tomorrow, tz)
        if departure is None:
            return None
        when = f"après ton départ (d'habitude vers {hm(departure)})"
        because = [f"habitude : départ vers {hm(departure)}"]
    because += [
        f"constat : {n} pas nettoyé{'e' if n.endswith('e') else ''} depuis {o.get('values', {}).get('days')} jours"
        for n, o in zip(names, due, strict=False)
    ]
    return Offer(
        kind=ROBOT_AWAY,
        question=f"Je lance le robot ({', '.join(names)}) {when}, quand la maison est vide ?",
        what=f"lancé le robot ({', '.join(names)})",
        gesture={
            "method": "POST",
            "path": f"/api/machines/{robot['id']}/commands",
            "body": {"action": "StartCleaning", "room_ids": rooms},
            "label": f"StartCleaning {robot['id']}",
        },
        after_away_min=AFTER_DEPARTURE_MIN,
        condition={"situation": "AWAY", "machine": robot["id"], "machine_status": "DOCKED"},
        because=because,
    )


def _close(rain_from: datetime | None, tz: ZoneInfo, house: dict) -> Offer | None:
    """Un volet ou un store ouvert et la pluie annoncée de jour : le fermer 30 min avant."""
    if rain_from is None:
        return None
    at = rain_from - BEFORE_RAIN
    if not DAYTIME[0] <= at.time() <= DAYTIME[1]:
        return None
    covers = [
        c
        for r in house.get("rooms", [])
        for c in r.get("covers", []) or []
        if (c.get("position") or 0) > 0 and c.get("available", True)
    ]
    if not covers:
        return None
    cover = covers[0]
    return Offer(
        kind=CLOSE_BEFORE_RAIN,
        question=f"Je ferme {cover.get('name') or cover['id']} à {hm(at)}, avant la pluie ?",
        what=f"fermé {cover.get('name') or cover['id']} avant la pluie",
        gesture={
            "method": "POST",
            "path": f"/api/covers/{cover['id']}/commands",
            "body": {"action": "SetPosition", "position": 0},
            "label": f"SetPosition {cover['id']} 0",
        },
        at=at.astimezone(UTC),
        condition={
            "cover": cover["id"],
            "cover_open": True,
            "rain_before": (rain_from + timedelta(hours=2)).astimezone(UTC).isoformat(),
        },
        because=[f"météo : pluie dès {hm(rain_from)}", f"{cover.get('name') or cover['id']} ouvert"],
    )


def _remind(tomorrow: date, tz: ZoneInfo, due: list[dict], habits: dict | None) -> Offer | None:
    """Un rappel de demain sans heure, et un départ habituel : le rappeler au moment de partir."""
    departure = habitual_departure(habits, tomorrow, tz)
    reminder = next((r for r in due if len(r.get("due") or "") <= 10 and r["due"][:10] == tomorrow.isoformat()), None)
    if departure is None or reminder is None:
        return None
    at = departure - timedelta(minutes=10)
    return Offer(
        kind=REMIND_AT_DEPARTURE,
        question=f"Je te rappelle « {reminder.get('title')} » vers {hm(at)}, avant de partir ?",
        what=f"rappelé « {reminder.get('title')} »",
        notify={"title": "En partant", "message": f"N'oublie pas : {reminder.get('title')}."},
        at=at.astimezone(UTC),
        condition={"reminder": reminder.get("id"), "reminder_open": True},
        because=[f"rappel : {reminder.get('title')}", f"habitude : départ vers {hm(departure)}"],
    )
