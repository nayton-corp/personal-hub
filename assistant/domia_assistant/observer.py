"""L'observateur et le brief du soir (spec §12) : toutes les heures, au plus une remarque, jamais la nuit ni pendant
une soirée TV ; un sujet déjà dit se tait 24 h, un sujet refusé une semaine puis le double. Le brief rassemble l'agenda
de demain, les rappels qui tombent et au plus deux points sur la maison. Les phrases sont fixes et chiffrées : un
modèle n'est pas nécessaire pour dire qu'une pile est faible."""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from . import planner
from .agenda import Agenda, AgendaUnavailable
from .domia import Domia, DomiaError
from .engagements import Engagements
from .library import Library
from .memory import Memory

ZONE = ZoneInfo("Europe/Zurich")

# l'ordre de priorité : ce qui casse avant ce qui encombre
ORDER = ["WINDOW_OPEN_RAIN", "BATTERY_LOW", "SENSOR_SILENT", "APPLIANCE_ON_LONG", "MAINTENANCE_DUE", "CLEANING_DUE"]


@dataclass(frozen=True)
class Remark:
    subject: str
    kind: str
    title: str
    message: str


def phrase(o: dict) -> Remark:
    """Un constat de Domia (ou d'entretien) en une remarque courte."""
    kind, name, v = o["kind"], o.get("subject_name") or o.get("subject"), o.get("values") or {}
    if kind == "CLEANING_DUE":
        text = f"{name} n'a pas été nettoyé{'e' if name and name.endswith('e') else ''} depuis {v.get('days')} jours. Je lance le robot quand vous sortez ?"
        return Remark(o["id"], kind, "Ménage", text)
    if kind == "APPLIANCE_ON_LONG":
        text = f"{name} est allumé depuis {v.get('hours')} h"
        if v.get("standby"):
            text += ", en veille"
        if v.get("power_w") is not None:
            text += f" ({round(v['power_w'])} W)"
        return Remark(o["id"], kind, "Appareil", text + ". Je l'éteins ?")
    if kind == "SENSOR_SILENT":
        hours = v.get("hours")
        return Remark(
            o["id"],
            kind,
            "Capteur",
            f"{name} ne donne plus de nouvelles" + (f" depuis {hours} h." if hours is not None else "."),
        )
    if kind == "BATTERY_LOW":
        return Remark(
            o["id"], kind, "Pile", f"La pile de {name} est à {round(v.get('battery_pct', 0))} %. À changer bientôt."
        )
    if kind == "WINDOW_OPEN_RAIN":
        rain = v.get("rain_from")
        when = ""
        if rain:
            local = datetime.fromisoformat(rain.replace("Z", "+00:00")).astimezone(ZONE)
            when = f" dès {local.hour} h" + (f" {local.minute:02d}" if local.minute else "")
        return Remark(o["id"], kind, "Fenêtre", f"{name} est ouverte et la pluie est annoncée{when}.")
    if kind == "MAINTENANCE_DUE":
        return Remark(o["id"], kind, "Entretien", f"{name} : {o.get('what')} (prévu depuis le {o.get('since')}).")
    return Remark(o["id"], kind, "Maison", f"{kind} : {name}")


def maintenance_observations(library: Library | None, today: date) -> list[dict]:
    if library is None:
        return []
    return [
        {
            "id": f"MAINTENANCE_DUE:{d['card']}:{d['what']}",
            "kind": "MAINTENANCE_DUE",
            "subject": d["card"],
            "subject_name": d["name"],
            "what": d["what"],
            "since": d["since"],
        }
        for d in library.maintenance_due(today)
    ]


def watching_tv(facts: dict) -> bool:
    for e in (facts.get("estimates") or {}).values():
        if e.get("kind") == "WATCHING_TV" and (e.get("fact") or {}).get("value") is True:
            return True
    return False


class Observer:
    def __init__(
        self,
        domia: Domia,
        memory: Memory,
        library: Library | None = None,
        agenda: Agenda | None = None,
        engagements: Engagements | None = None,
        zone: str = "Europe/Zurich",
    ):
        self.domia = domia
        self.memory = memory
        self.library = library
        self.agenda = agenda
        self.engagements = engagements
        self.zone = zone

    def quiet_now(self) -> str | None:
        """Pourquoi se taire maintenant, ou None."""
        situation = (self.domia.house().get("situation") or {}).get("value")
        if situation == "NIGHT":
            return "nuit"
        if watching_tv(self.domia.facts()):
            return "soirée TV"
        return None

    def candidates(self, now: datetime) -> list[Remark]:
        found = self.domia.observations() + maintenance_observations(self.library, now.date())
        found = [o for o in found if not self.memory.quiet(o["id"], now)]
        found.sort(key=lambda o: ORDER.index(o["kind"]) if o["kind"] in ORDER else len(ORDER))
        return [phrase(o) for o in found]

    def run_once(self, now: datetime | None = None) -> Remark | None:
        """Un réveil : au plus une remarque, envoyée par les notifications de Domia."""
        now = now or datetime.now(UTC)
        if self.quiet_now():
            return None
        for remark in self.candidates(now):
            try:
                self.domia.notify(remark.title, remark.message)
            except DomiaError as e:
                if e.code in ("NIGHT", "NO_RECIPIENT"):
                    return None
                raise
            self.memory.said(remark.subject, now)
            return remark
        return None

    def plan(self, now: datetime, tomorrow: date) -> tuple[planner.Plan, list[str]]:
        """Le plan de demain (spec « préparer demain » §5), et ce qui a manqué pour le faire (Rappels, météo)."""
        missing: list[str] = []
        events: list[dict] = []
        reminders: list[dict] = []
        if self.agenda:
            try:
                events = self.agenda.calendar(tomorrow.isoformat(), (tomorrow + timedelta(days=1)).isoformat())
                reminders = self.agenda.reminders()
            except AgendaUnavailable:
                missing.append("(Rappels et Calendrier non autorisés.)")
        weather = habits = None
        try:
            weather = self.domia.weather()
        except DomiaError:
            missing.append("(Pas de météo.)")
        with contextlib.suppress(DomiaError):
            habits = self.domia.habits()
        observations = self.domia.observations()
        p = planner.plan(tomorrow, self.zone, events, reminders, weather, habits, observations, self.domia.house())
        if len(p.lines) < planner.MAX_LINES:
            told = {o["id"] for o in observations if o.get("kind") == "WINDOW_OPEN_RAIN"}
            told |= {
                o["id"]
                for o in observations
                if o.get("kind") == "CLEANING_DUE" and any(x.kind == planner.ROBOT_AWAY for x in p.offers)
            }
            others = [r for r in self.candidates(now) if r.subject not in told]
            p.lines += [r.message for r in others[: planner.MAX_LINES - len(p.lines)][:2]]
        return p, missing

    def brief(self, now: datetime, tomorrow: date) -> str | None:
        """Le brief du soir : le plan de demain et au plus deux propositions, qui attendent un « oui »."""
        p, missing = self.plan(now, tomorrow)
        if not p.lines and not p.offers:
            return None
        if self.engagements and p.offers:
            self.engagements.offer(p, tomorrow, now)
        message = " ".join(p.lines + missing + [o.question for o in p.offers])[:600]
        self.domia.notify("Demain", message)
        return message
