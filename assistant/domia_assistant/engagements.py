"""Les engagements (spec « préparer demain » §6) : un « oui » ce soir, tenu demain. L'assistant joue le geste au nom de
la personne qui a dit oui, à son heure ou 15 min après le passage en Absent, et seulement si sa condition tient encore ;
sinon il ne joue rien et le dit une fois. Un engagement expire à minuit le lendemain. Le geste passe par l'API de
Domia comme tout geste de l'assistant : l'arbitre, les lois et le Manuel décident toujours."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from .agenda import Agenda, AgendaUnavailable
from .domia import Domia, DomiaError
from .memory import ACCEPTED, CANCELLED, DONE, EXPIRED, OFFERED, REFUSED, SKIPPED, Memory
from .planner import Plan

LOG = logging.getLogger("assistant")

LATE = timedelta(minutes=30)  # une heure manquée de plus (la machine IA éteinte) : trop tard


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat() if value else None


def _when(raw: str) -> datetime:
    return datetime.fromisoformat(raw.replace("Z", "+00:00"))


def _at(raw: str | None) -> datetime | None:
    return _when(raw) if raw else None


class Engagements:
    def __init__(self, domia: Domia, memory: Memory, agenda: Agenda | None = None, zone: str = "Europe/Zurich"):
        self.domia = domia
        self.memory = memory
        self.agenda = agenda
        self.tz = ZoneInfo(zone)

    # proposer, accepter, annuler
    def offer(self, plan: Plan, tomorrow: date, now: datetime) -> list[int]:
        """Les propositions d'un plan, en attente d'un « oui » jusqu'à minuit demain ; un nouveau plan remplace les
        propositions restées sans réponse."""
        for e in self.memory.engagements(OFFERED):
            self.memory.settle(e["id"], EXPIRED, outcome="remplacée par un nouveau plan")
        expires = datetime.combine(tomorrow + timedelta(days=1), time(0, 0), self.tz)
        ids = []
        for o in plan.offers:
            body = {k: v for k, v in asdict(o).items() if k not in ("kind", "question")}
            body["at"] = _iso(o.at)
            ids.append(self.memory.offer(o.kind, o.question, json.dumps(body, ensure_ascii=False), expires, now))
        return ids

    def waiting(self, now: datetime) -> list[dict]:
        """Les propositions qui attendent encore un « oui »."""
        return [e for e in self.memory.engagements(OFFERED) if _when(e["expires"]) > now]

    def accept(self, engagement_id: int | None, person: str | None, now: datetime) -> list[dict]:
        """« Oui » : une proposition, ou toutes celles qui attendent ; rend celles acceptées."""
        chosen = [e for e in self.waiting(now) if engagement_id is None or e["id"] == engagement_id]
        return [e for e in chosen if self.memory.settle(e["id"], ACCEPTED, person=person, only_from=(OFFERED,))]

    def refuse(self, now: datetime) -> int:
        return sum(self.memory.settle(e["id"], REFUSED, only_from=(OFFERED,)) for e in self.waiting(now))

    def cancel(self, engagement_id: int) -> bool:
        return self.memory.settle(engagement_id, CANCELLED, only_from=(OFFERED, ACCEPTED))

    def decide(self, engagement_id: int, decision: str, person: str | None, now: datetime) -> bool:
        """Un bouton de l'écran (spec de l'écran §5) : accepter, refuser ou annuler un engagement, sans le modèle."""
        if decision == "ACCEPT":
            return bool(self.accept(engagement_id, person, now))
        if decision == "REFUSE":
            return any(e["id"] == engagement_id for e in self.waiting(now)) and self.memory.settle(
                engagement_id, REFUSED, only_from=(OFFERED,)
            )
        if decision == "CANCEL":
            return self.cancel(engagement_id)
        raise ValueError(decision)

    def listing(self, now: datetime) -> list[dict]:
        """Ce qui est prévu (accepté) ou proposé, pour « qu'est-ce que tu as prévu ? » et l'écran « Ce qui est
        prévu » ; `accepted` et `at` (ou `after_away_min`) pour l'écran."""
        out = []
        for e in self.memory.engagements(OFFERED, ACCEPTED):
            if _when(e["expires"]) <= now:
                continue
            offer = json.loads(e["offer"])
            out.append(
                {
                    "id": e["id"],
                    "state": "prévu" if e["state"] == ACCEPTED else "proposé, sans réponse",
                    "accepted": e["state"] == ACCEPTED,
                    "question": e["question"],
                    "what": offer.get("what"),
                    "at": offer.get("at"),
                    "after_away_min": offer.get("after_away_min"),
                    "because": offer.get("because"),
                    "by": e["person"],
                }
            )
        return out

    # tenir
    def tick(self, now: datetime) -> list[str]:
        """Un tour d'horloge : joue ce qui est dû et dont la condition tient ; rend ce qui a été dit."""
        said: list[str | None] = []
        accepted = self.memory.engagements(ACCEPTED)
        if not accepted:
            return []
        house = self.domia.house()
        situation = house.get("situation") or {}
        for e in accepted:
            offer = json.loads(e["offer"])
            if now >= _when(e["expires"]):
                why = (
                    "la maison n'a jamais été vide"
                    if offer.get("after_away_min") is not None
                    else "le moment n'est jamais venu"
                )
                said.append(self._end(e, offer, EXPIRED, why))
                continue
            if offer.get("at"):
                at = _when(offer["at"])
                if now < at:
                    continue
                if now > at + LATE:
                    said.append(self._end(e, offer, SKIPPED, "c'était trop tard"))
                    continue
            elif offer.get("after_away_min") is not None:
                if situation.get("value") != "AWAY":
                    if e["armed_at"]:
                        self.memory.disarm(e["id"])  # revenu avant l'heure : on attend le prochain départ
                    continue
                armed = _at(e["armed_at"])
                if armed is None:
                    armed = _at(situation.get("updated_at")) or now
                    self.memory.settle(e["id"], ACCEPTED, armed_at=armed)
                if now < armed + timedelta(minutes=offer["after_away_min"]):
                    continue
            ok, why = self._holds(offer.get("condition") or {}, house)
            if not ok:
                said.append(self._end(e, offer, SKIPPED, why))
                continue
            said.append(self._play(e, offer))
        return [s for s in said if isinstance(s, str) and s]

    def _holds(self, condition: dict, house: dict) -> tuple[bool, str]:
        situation = (house.get("situation") or {}).get("value")
        if situation == "NIGHT":
            return False, "c'est la nuit"
        if condition.get("situation") and situation != condition["situation"]:
            return False, "quelqu'un est resté à la maison"
        if condition.get("machine"):
            robot = next((m for m in house.get("machines", []) or [] if m["id"] == condition["machine"]), None)
            if robot is None or robot.get("status") != condition.get("machine_status", "DOCKED"):
                return False, "le robot n'était pas à sa base"
        if condition.get("cover"):
            cover = next(
                (c for r in house.get("rooms", []) for c in r.get("covers", []) or [] if c["id"] == condition["cover"]),
                None,
            )
            if cover is None or not (cover.get("position") or 0) > 0:
                return False, "il était déjà fermé"
        if condition.get("rain_before"):
            try:
                weather = self.domia.weather()
            except DomiaError:
                weather = {}
            rain = _at(weather.get("rain_from")) if not weather.get("stale") and not weather.get("reason") else None
            if rain is None or rain > _when(condition["rain_before"]):
                return False, "la pluie n'est plus annoncée"
        if condition.get("reminder"):
            try:
                open_ids = {r.get("id") for r in (self.agenda.reminders() if self.agenda else [])}
            except AgendaUnavailable:
                return False, "je ne lis plus les Rappels"
            if condition["reminder"] not in open_ids:
                return False, "il est déjà coché"
        return True, ""

    def _play(self, e: dict, offer: dict) -> str | None:
        try:
            if offer.get("gesture"):
                g = offer["gesture"]
                self.domia.gesture(g["method"], g["path"], g["body"], e["person"])
                message = f"C'est fait : j'ai {offer['what']}, comme convenu."
                self._say(message)
            else:
                self.domia.notify(offer["notify"]["title"], offer["notify"]["message"])
                message = offer["notify"]["message"]
        except DomiaError as err:
            return self._end(e, offer, SKIPPED, f"Domia a refusé ({err.message or err.code})")
        self.memory.settle(e["id"], DONE, outcome="joué")
        LOG.info("engagement_done id=%s kind=%s", e["id"], e["kind"])
        return message

    def _end(self, e: dict, offer: dict, state: str, why: str) -> str:
        self.memory.settle(e["id"], state, outcome=why)
        LOG.info("engagement_%s id=%s kind=%s why=%s", state.lower(), e["id"], e["kind"], why)
        message = f"Je n'ai pas {offer['what']} : {why}."
        self._say(message)
        return message

    def _say(self, message: str) -> None:
        try:
            self.domia.notify("Prévu hier soir", message)
        except DomiaError as e:
            LOG.info("engagement_notice_dropped code=%s", e.code)
