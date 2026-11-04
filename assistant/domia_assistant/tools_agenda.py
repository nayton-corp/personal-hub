"""Les outils du temps et du dehors : Rappels et Calendrier (pont du Mac), la recherche web (la question seule
sort), et le plan de demain (proposer, accepter, annuler)."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from .agenda import Agenda, AgendaUnavailable
from .domia import Domia
from .tools_base import Speaker, Tool, obj


def agenda_tools(agenda: Agenda) -> list[Tool]:
    def guarded(fn: Callable[[dict[str, Any], Speaker], Any]) -> Callable[[dict[str, Any], Speaker], Any]:
        def run(args: dict[str, Any], who: Speaker) -> Any:
            try:
                return fn(args, who)
            except AgendaUnavailable as e:
                return {"error": f"Rappels non autorisés ou injoignables : {e}"}

        return run

    when = {"type": "string", "description": "date ou date-heure ISO 8601, heure locale"}
    return [
        Tool(
            "reminders",
            "Les rappels ouverts d'une liste (« Courses » par défaut si on parle de courses), ou de toutes.",
            obj({"list": {"type": "string"}}),
            guarded(lambda a, w: agenda.reminders(a.get("list"))),
        ),
        Tool(
            "add_reminder",
            "Ajoute un rappel, une fois. list « Courses » pour ce qui s'achète ; sinon pas de list (la liste par défaut). Échéance et récurrence possibles : recurrence daily, weekly, monthly ou yearly, interval pour « toutes les 2 semaines » (weekly, 2).",
            obj(
                {
                    "title": {"type": "string"},
                    "list": {"type": "string"},
                    "due": when,
                    "recurrence": {"type": "string", "enum": ["daily", "weekly", "monthly", "yearly"]},
                    "interval": {"type": "integer", "minimum": 1, "maximum": 52},
                    "notes": {"type": "string"},
                },
                ["title"],
            ),
            guarded(
                lambda a, w: agenda.add_reminder(
                    a["title"], a.get("list"), a.get("due"), a.get("recurrence"), a.get("interval"), a.get("notes")
                )
            ),
        ),
        Tool(
            "complete_reminder",
            "Coche un rappel par son id. Jamais de suppression.",
            obj({"id": {"type": "string"}}, ["id"]),
            guarded(lambda a, w: agenda.complete_reminder(a["id"])),
        ),
        Tool(
            "calendar",
            "Les événements du calendrier entre deux dates.",
            obj({"from": when, "to": when}, ["from", "to"]),
            guarded(lambda a, w: agenda.calendar(a["from"], a["to"])),
        ),
        Tool(
            "add_event",
            "Ajoute un événement au calendrier.",
            obj(
                {
                    "title": {"type": "string"},
                    "start": when,
                    "end": when,
                    "calendar": {"type": "string"},
                    "notes": {"type": "string"},
                },
                ["title", "start", "end"],
            ),
            guarded(lambda a, w: agenda.add_event(a["title"], a["start"], a["end"], a.get("calendar"), a.get("notes"))),
        ),
    ]


def web_tools(searx_url: str | None) -> list[Tool]:
    """La recherche web (décision 5) : la question seule sort, jamais l'état de la maison ; seulement si la
    bibliothèque n'a rien."""
    if not searx_url:
        return []

    def search(args: dict[str, Any], who: Speaker) -> Any:
        url = searx_url.rstrip("/") + "/search?" + urllib.parse.urlencode({"q": args["query"], "format": "json"})
        try:
            with urllib.request.urlopen(url, timeout=15) as response:
                results = json.loads(response.read()).get("results", [])
        except (urllib.error.URLError, TimeoutError, ValueError) as e:
            return {"error": f"la recherche web ne répond pas ({e})"}
        return [{"title": r.get("title"), "url": r.get("url"), "content": r.get("content")} for r in results[:5]]

    return [
        Tool(
            "web_search",
            "Cherche sur le web (un manuel, un code d'erreur) quand la bibliothèque n'a rien. N'y mettre que la question, jamais l'état de la maison.",
            obj({"query": {"type": "string"}}, ["query"]),
            search,
        )
    ]


def planning_tools(
    domia: Domia, plan: Callable[[datetime, Any], Any] | None, engagements: Any | None, zone: str = "Europe/Zurich"
) -> list[Tool]:
    """Demain (spec « préparer demain ») : la météo, les habitudes, le plan et ses propositions, ce qui est prévu."""
    tools = [
        Tool(
            "weather",
            "La météo de la maison : aujourd'hui, demain, les 48 prochaines heures, la première pluie.",
            obj({}),
            lambda a, w: domia.weather(),
        ),
        Tool(
            "habits",
            "Les heures habituelles du foyer par jour de semaine : coucher, lever, départ, retour, et la part des jours avec un départ.",
            obj({"days": {"type": "integer", "minimum": 7, "maximum": 90}}),
            lambda a, w: domia.habits(int(a.get("days", 28))),
        ),
    ]
    if plan is None or engagements is None:
        return tools

    def tomorrow(args: dict[str, Any], who: Speaker) -> Any:
        now = datetime.now(UTC)
        day = datetime.now(ZoneInfo(zone)).date() + timedelta(days=1)
        p, missing = plan(now, day)
        ids = engagements.offer(p, day, now)
        return {
            "plan": p.lines + missing,
            "proposals": [
                {"id": i, "question": o.question, "because": o.because} for i, o in zip(ids, p.offers, strict=False)
            ],
        }

    def accept(args: dict[str, Any], who: Speaker) -> Any:
        done = engagements.accept(args.get("id"), who.person, datetime.now(UTC))
        return (
            {"accepted": [e["question"] for e in done]}
            if done
            else {"error": "aucune proposition en attente avec cet id"}
        )

    def cancel(args: dict[str, Any], who: Speaker) -> Any:
        return {"cancelled": engagements.cancel(int(args["id"]))}

    return [
        *tools,
        Tool(
            "plan_tomorrow",
            "Le plan de demain : agenda, météo, habitudes, constats, et au plus deux propositions (robot pendant l'absence, fermer avant la pluie, rappel au départ) qui attendent un oui.",
            obj({}),
            tomorrow,
        ),
        Tool(
            "planned",
            "Ce qui est prévu pour demain (propositions acceptées) et les propositions sans réponse, avec leur id et leur raison.",
            obj({}),
            lambda a, w: engagements.listing(datetime.now(UTC)),
        ),
        Tool(
            "accept_planned",
            "La personne dit oui à une proposition du plan (son id), ou à toutes si pas d'id.",
            obj({"id": {"type": "integer"}}),
            accept,
        ),
        Tool(
            "cancel_planned",
            "Annule une chose prévue par son id (« annule le robot »).",
            obj({"id": {"type": "integer"}}, ["id"]),
            cancel,
        ),
    ]
