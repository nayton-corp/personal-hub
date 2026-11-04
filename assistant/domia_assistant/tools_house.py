"""Les outils de la maison : les gestes, générés depuis `GET /api/commands/catalog` (§7.2, jamais de `Toggle`,
chaque geste au nom de la personne qui parle), et les lectures (maison, faits, nuits, activité, pourquoi, réglages,
état, notifications, estimations, entités HA, test de notification)."""

from __future__ import annotations

import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from . import reading
from .domia import Domia
from .tools_base import GLOSS, HOUSE_WIDE_SITUATIONS, Speaker, Tool, compact_house, field_schema, obj, snake


def gesture_tools(catalog: dict[str, Any], house: dict[str, Any], domia: Domia) -> list[Tool]:
    """Un outil par route du catalogue ; `action` choisit le geste quand la route en porte plusieurs."""
    fields = catalog.get("fields", {})
    ids = {
        "LIGHT": [lamp["id"] for r in house.get("rooms", []) for lamp in r.get("lights", [])],
        "APPLIANCE": [a["id"] for r in house.get("rooms", []) for a in r.get("appliances", []) or []],
        "COVER": [c["id"] for r in house.get("rooms", []) for c in r.get("covers", []) or []],
        "EMITTER": [e["id"] for r in house.get("rooms", []) for e in r.get("emitters", []) or []],
        "MACHINE": [m["id"] for m in house.get("machines", []) or []],
        "ROOM": [r["id"] for r in house.get("rooms", [])],
        "PERSON": [p.get("id") for p in house.get("people", []) or [] if p.get("id")],
    }
    tools: list[Tool] = []
    for route in catalog.get("routes", []):
        kind, method, path = route["kind"], route["method"], route["path"]
        in_body = route.get("action_in_body", route.get("actionInBody", False))
        # « garder tel quel » et la fin d'un Manuel (`until`) restent à la voie rapide et aux écrans : au banc, le modèle
        # les prenait pour « éteindre plus tard » ou « sauf » (spec de l'assistant complet §16.12)
        gestures = [g for g in route.get("gestures", []) if not g["id"].startswith("Toggle") and g["id"] != "KeepAsIs"]
        if not gestures or (kind in ids and not ids[kind]):
            continue
        props: dict[str, Any] = {}
        required: list[str] = []
        if "{id}" in path:
            props["id"] = {"type": "string", **({"enum": ids[kind]} if kind in ids else {})}
            required.append("id")
        if in_body:
            props["action"] = {"type": "string", "enum": [g["id"] for g in gestures]}
            required.append("action")
        for g in gestures:
            for f in g.get("fields", []) + [o for o in g.get("options", []) if o != "until"]:
                props.setdefault(f, field_schema(fields.get(f, {})))
            if not in_body:
                required += [f for f in g.get("fields", []) if f not in required]
        lines = [f"{g['id']}({', '.join(g.get('fields', []))}){GLOSS.get(g['id'], '')}" for g in gestures]
        name = f"{kind.lower()}_command" if in_body else snake(gestures[0]["id"])
        if name in {t.name for t in tools}:
            name = f"{kind.lower()}_{snake(gestures[0]['id'])}"
        description = f"Geste Domia ({kind}) : {'; '.join(lines)}. Joué au nom de la personne qui parle."

        def run(
            args: dict[str, Any],
            who: Speaker,
            path: str = path,
            method: str = method,
            in_body: bool = in_body,
            gestures: list[dict[str, Any]] = gestures,
        ) -> Any:
            args = dict(args)
            target = path.replace("{id}", urllib.parse.quote(str(args.pop("id", "")), safe=""))
            body = {k: v for k, v in args.items() if v is not None}
            if not in_body:
                body.pop("action", None)
            elif body.get("action") == "TurnOn":
                # « allume à 30 % » : le modèle envoie TurnOn avec une valeur qu'il ne porte pas ; le geste qui la porte
                wanted = [g["id"] for g in gestures if g.get("fields") and all(f in body for f in g["fields"])]
                if len(wanted) == 1:
                    body["action"] = wanted[0]
            return domia.gesture(method, target, body or ({} if method != "GET" else None), who.person)

        def house_wide(args: dict[str, Any], kind: str = kind) -> bool:
            return kind == "HOUSE" and args.get("value") in HOUSE_WIDE_SITUATIONS

        tools.append(Tool(name, description, obj(props, required), run, gesture=True, house_wide=house_wide))
    return tools


def read_tools(domia: Domia, zone: str = "Europe/Zurich") -> list[Tool]:
    """Savoir la maison (spec de l'assistant complet §4) : chaque lecture vise (pièce, sorte, objet, période)."""
    tz = ZoneInfo(zone)

    def settings() -> reading.Settings:
        return reading.Settings(domia.config())

    def house(args: dict[str, Any], who: Speaker) -> Any:
        raw = domia.house()
        return reading.house_view(raw, compact_house(raw), args.get("room"), args.get("kind"))

    def facts(args: dict[str, Any], who: Speaker) -> Any:
        all_facts = domia.facts()
        topic = args.get("topic")
        if topic:
            return (
                {topic: all_facts.get(topic)} if topic in all_facts else {"error": f"sujets : {', '.join(all_facts)}"}
            )
        # sans sujet : la liste des sujets et les faits de la maison entière, pas ceux de chaque pièce
        return {
            "sujets": [k for k, v in all_facts.items() if v not in (None, {}, [])],
            "nuit": all_facts.get("night"),
            "foyer": all_facts.get("household"),
        }

    def nights(args: dict[str, Any], who: Speaker) -> Any:
        """Les changements de situation, en heure locale : en quelques lignes ce que le journal dit en milliers de jetons."""
        today = datetime.now(tz).date()
        days = min(max(int(args.get("days", 7)), 1), 31)
        lines = domia.memory((today - timedelta(days=days - 1)).isoformat(), today.isoformat())
        return reading.situations(lines, tz) or "aucun changement de situation ces jours-là"

    def activity(args: dict[str, Any], who: Speaker, limit: int = 12) -> Any:
        end = datetime.now(UTC)
        start = end - timedelta(hours=min(max(int(args.get("hours", 24)), 1), 48))
        conf = settings().config
        entities: dict[str, str] = {}
        rooms: dict[str, set[str]] = {}
        acting: set[str] = set()  # sans objet visé, les objets qui agissent : les capteurs changent sans cesse
        for r in conf.get("rooms") or []:
            for plural in reading.OBJECT_KINDS:
                for o in r.get(plural) or []:
                    for key in ("ha_entity_id", "power_sensor"):
                        if o.get(key):
                            entities[o[key]] = o.get("id")
                    if plural != "sensors" and o.get("ha_entity_id"):
                        acting.add(o["ha_entity_id"])
                    rooms.setdefault(r["id"], set()).update({o.get("id"), o.get("ha_entity_id")} - {None})
        wanted: set[str] | None = None
        if args.get("object"):
            wanted = {args["object"]} | {e for e, i in entities.items() if i == args["object"]}
        if args.get("room"):
            room = next(
                (r["id"] for r in conf.get("rooms") or [] if reading._match(args["room"], r["id"], r.get("name"))), None
            )
            wanted = (wanted or set()) | rooms.get(room or "", set()) | ({room} if room else set())
        asked = [e for e in wanted if "." in e] if wanted is not None else sorted(acting)
        lines = domia.journal(start.isoformat(), end.isoformat(), ["command", "entity_change"], asked or ["-"])
        out = reading.activity(lines, tz, entities, wanted, limit)
        out["période"] = f"{min(max(int(args.get('hours', 24)), 1), 48)} h"
        return out

    def why(args: dict[str, Any], who: Speaker) -> Any:
        out = activity({"object": args["object"], "hours": 24}, who, limit=6)
        raw = domia.house()
        for r in raw.get("rooms", []):
            for plural in ("lights", "appliances", "covers", "emitters"):
                for o in r.get(plural, []) or []:
                    if o.get("id") == args["object"]:
                        out["maintenant"] = {
                            k: o.get(k)
                            for k in ("on", "brightness_pct", "position", "mode", "hold", "reason", "law")
                            if o.get(k) is not None
                        }
                        out["pièce"] = {"id": r["id"], "occupation": r.get("occupancy")}
        out["situation"] = (raw.get("situation") or {}).get("value")
        return out

    def read_settings(args: dict[str, Any], who: Speaker) -> Any:
        s = settings()
        kind = args.get("kind")
        if not kind:
            return s.index()
        out = s.entry(kind, args.get("id"))
        out["revision"] = s.revision
        if args.get("explain"):
            out["aide"] = reading.explain(kind, args.get("field"))
        return out

    def status(args: dict[str, Any], who: Speaker) -> Any:
        return reading.health_view(domia.health(), domia.memory_summary())

    def notifications(args: dict[str, Any], who: Speaker) -> Any:
        out: dict[str, Any] = {
            "envoyées": reading.notification_view(domia.notifications(), tz, min(max(int(args.get("days", 7)), 1), 30))
        }
        if args.get("services"):
            out["services"] = domia.notify_services()
        return out

    def estimates(args: dict[str, Any], who: Speaker) -> Any:
        models = settings().config.get("estimates") or []
        now = domia.facts().get("estimates") or {}

        def current(id: str) -> dict[str, Any]:
            last = (now.get(id) or {}).get("last") or {}
            return {k: last.get(k) for k in ("value", "confidence", "because", "at") if last.get(k) is not None}

        out = [
            {
                "id": e.get("id"),
                "sorte": e.get("kind"),
                "pièce": e.get("room"),
                "mode": e.get("mode"),
                "maintenant": current(e.get("id")),
            }
            for e in models
        ]
        # un id de personne ou de pièce n'est pas un modèle : toutes les estimations plutôt qu'un « pas trouvé »
        return (
            {
                "note": f"« {args['id']} » n'est pas un modèle d'estimation : voici toutes les estimations",
                "estimations": out,
            }
            if args.get("id")
            else out
        )

    def ha(args: dict[str, Any], who: Speaker) -> Any:
        return reading.ha_view(domia.ha_entities(), settings().entities(), args.get("domain"), bool(args.get("unused")))

    def test_notification(args: dict[str, Any], who: Speaker) -> Any:
        conf = settings().config
        found = reading.recipients_for(conf, args.get("to"), who.person)
        if isinstance(found, str):
            names = [r.get("name") or r.get("id") for r in (conf.get("notifications") or {}).get("recipients") or []]
            return {"error": found, "destinataires": names}
        for r in found[:3]:
            domia.notify_test(r["service"], who.person)
        return {"envoyée à": [r.get("name") or r.get("id") for r in found[:3]]}

    kinds = sorted(set(reading.KINDS) | set(reading.LISTED) | set(reading.SINGLE))
    return [
        Tool(
            "house",
            "L'état de la maison en court : situation, pièces (occupation, température, lampes, appareils, volets, chauffage), robots, qui est là. Vise une pièce (id ou nom) ou une sorte (lights, appliances, covers, emitters, machines, people).",
            obj(
                {
                    "room": {"type": "string"},
                    "kind": {
                        "type": "string",
                        "enum": ["lights", "appliances", "covers", "emitters", "machines", "people"],
                    },
                }
            ),
            house,
        ),
        Tool(
            "facts",
            "Les faits partagés de Domia : sans `topic`, la nuit, le foyer et la liste des sujets ; avec `topic` (rooms, openings, appliances, sensors…), ce sujet.",
            obj({"topic": {"type": "string"}}),
            facts,
        ),
        Tool(
            "activity",
            "Ce qui s'est passé ces dernières heures (48 h au plus), en agrégats : les gestes (qui, quoi, quand) et, par objet, ses changements et son dernier état. Vise un objet (id) ou une pièce.",
            obj(
                {
                    "hours": {"type": "integer", "minimum": 1, "maximum": 48},
                    "object": {"type": "string"},
                    "room": {"type": "string"},
                }
            ),
            activity,
        ),
        Tool(
            "why",
            "Pourquoi un objet est dans cet état : son état et son mode, les gestes et changements des dernières 24 h, la pièce, la situation.",
            obj({"object": {"type": "string"}}, ["object"]),
            why,
        ),
        Tool(
            "situations",
            "Les passages en Nuit, Jour et Absent des derniers jours, en heure locale : l'heure du coucher (→ Nuit), du lever (Nuit → Jour), des départs.",
            obj({"days": {"type": "integer", "minimum": 1, "maximum": 31}}),
            nights,
        ),
        Tool(
            "observations",
            "Les constats chiffrés du moment (nettoyage dû, appareil allumé longtemps, capteur muet, pile faible, fenêtre ouverte avant la pluie).",
            obj({}),
            lambda a, w: domia.observations(),
        ),
        Tool(
            "settings",
            "Les réglages de Domia (lecture) : sans argument, l'index des objets ; avec `kind` et `id`, les réglages d'un objet (délais en secondes) ; `explain` ajoute ce que veut dire chaque champ (ou `field`).",
            obj(
                {
                    "kind": {"type": "string", "enum": kinds},
                    "id": {"type": "string"},
                    "explain": {"type": "boolean"},
                    "field": {"type": "string"},
                }
            ),
            read_settings,
        ),
        Tool(
            "system_status",
            "La santé de Domia : HA joignable, disque, alertes (capteurs muets, entités manquantes), version, la mémoire gardée.",
            obj({}),
            status,
        ),
        Tool(
            "notifications",
            "Les notifications envoyées ces derniers jours (titre, statut : envoyée, retenue la nuit, abandonnée) ; `services` liste les services de notification.",
            obj({"days": {"type": "integer", "minimum": 1, "maximum": 30}, "services": {"type": "boolean"}}),
            notifications,
        ),
        Tool(
            "estimates",
            "Ce que Domia devine maintenant (TV regardée, au lit = IN_BED) et sa confiance, par estimation déclarée.",
            obj({"id": {"type": "string"}}),
            estimates,
        ),
        Tool(
            "ha_entities",
            "Les entités de Home Assistant, et si Domia s'en sert ; `unused` : seulement celles que Domia ne connaît pas ; `domain` : light, switch, sensor, binary_sensor, cover…",
            obj({"domain": {"type": "string"}, "unused": {"type": "boolean"}}),
            ha,
        ),
        Tool(
            "test_notification",
            "Envoie une notification d'essai. Sans `to`, à la personne qui parle ; sinon `to` = un prénom ou le nom d'un destinataire (« Kim », « iPad de Robin »).",
            obj({"to": {"type": "string"}}),
            test_notification,
            gesture=True,
        ),
    ]
