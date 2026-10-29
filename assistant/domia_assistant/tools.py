"""Les outils de l'assistant (spec §7) : un catalogue fermé, le même pour la boucle du modèle et le serveur MCP. Les
gestes sont générés depuis `GET /api/commands/catalog` (§7.2) : un geste ajouté à Domia arrive ici sans toucher
l'assistant ; jamais de `Toggle`. Chaque geste part au nom de la personne qui parle ; ceux qui touchent toute la maison
attendent un « oui » (§5.1)."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from . import reading
from .agenda import Agenda, AgendaUnavailable
from .domia import Domia, DomiaError
from .library import Library
from .memory import Memory
from .settings import NOUNS, Settler

HOUSE_WIDE_SITUATIONS = {"AWAY"}
# Les deux gestes que les modèles confondent : garder la main (Manuel) et la rendre à l'automatique.
GLOSS = {"Release": " = rendre à l'automatique"}
KIND_PARAM = {
    "LIGHT": "light",
    "APPLIANCE": "appliance",
    "COVER": "cover",
    "EMITTER": "emitter",
    "MACHINE": "machine",
    "ROOM": "room",
}


@dataclass(frozen=True)
class Speaker:
    """Qui parle (spec §4.2) : sa personne (None pour un micro de pièce, lot 2), la pièce si on la connaît."""

    person: str | None = None
    room: str | None = None
    client: str | None = None


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    run: Callable[[dict, Speaker], Any]
    gesture: bool = False
    house_wide: Callable[[dict], bool] = field(default=lambda args: False)
    family: str | None = None  # un outil du hub : son domaine est son type de demande
    allowed: Callable[[Speaker | None], bool] = field(default=lambda who: True)  # qui le voit et l'appelle

    @property
    def families(self) -> frozenset[str]:
        """Les types de demande où le modèle voit cet outil (le modèle en deux temps)."""
        if self.family is not None:
            return frozenset({self.family})
        return (
            frozenset({"gestes"})
            if self.gesture and self.name not in FAMILY_OF
            else FAMILY_OF.get(self.name, frozenset(FAMILIES))
        )

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {"name": self.name, "description": self.description, "parameters": self.parameters},
        }


def obj(properties: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": properties, "required": required or [], "additionalProperties": False}


def compact_house(house: dict) -> dict:
    """La maison en court pour le modèle : ce qui est allumé, ouvert, réglé, et qui est là."""
    rooms = []
    for r in house.get("rooms", []):
        room = {"id": r["id"], "name": r.get("name"), "occupancy": r.get("occupancy")}
        for key in ("temperature", "humidity", "co2", "lux"):
            if r.get(key) is not None:
                room[key] = r[key]
        room["lights"] = [
            {
                k: v
                for k, v in {
                    "id": lamp["id"],
                    "name": lamp.get("name"),
                    "on": lamp.get("on"),
                    "brightness_pct": lamp.get("brightness_pct"),
                    "dimmable": lamp.get("dimmable"),
                    "mode": (lamp.get("mode") or {}).get("value")
                    if isinstance(lamp.get("mode"), dict)
                    else lamp.get("mode"),
                }.items()
                if v is not None
            }
            for lamp in r.get("lights", [])
        ]
        for key, fields in (
            ("appliances", ("on", "standby")),
            ("covers", ("position",)),
            ("emitters", ("setpoint_c", "mode")),
        ):
            items = [
                {"id": o["id"], "name": o.get("name"), **{f: o.get(f) for f in fields if o.get(f) is not None}}
                for o in r.get(key, []) or []
            ]
            if items:
                room[key] = items
        rooms.append(room)
    machines = [
        {
            "id": m["id"],
            "name": m.get("name"),
            "status": m.get("status"),
            "battery": m.get("battery"),
            "rooms": m.get("cleanable_rooms"),
        }
        for m in house.get("machines", []) or []
    ]
    people = [{"id": p.get("id"), "name": p.get("name"), "home": p.get("home")} for p in house.get("people", []) or []]
    return {
        "situation": (house.get("situation") or {}).get("value"),
        "rooms": rooms,
        "machines": machines,
        "people": people,
    }


def field_schema(spec: dict) -> dict:
    kind = spec.get("type")
    out: dict[str, Any]
    if kind in ("int", "color"):
        out = {"type": "integer"}
    elif kind == "decimal":
        out = {"type": "number"}
    elif kind == "enum":
        out = {"type": "string", "enum": spec.get("values") or []}
    elif kind == "bool":
        out = {"type": "boolean"}
    elif kind == "refs":
        out = {"type": "array", "items": {"type": "string"}, "description": f"ids de {spec.get('of')}"}
    elif kind == "ref":
        out = {"type": "string", "description": f"id de {spec.get('of')}"}
    else:
        out = {"type": "object"}
    if spec.get("min") is not None:
        out["minimum"] = spec["min"]
    if spec.get("max") is not None:
        out["maximum"] = spec["max"]
    return out


def gesture_tools(catalog: dict, house: dict, domia: Domia) -> list[Tool]:
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
        name = f"{kind.lower()}_command" if in_body else _snake(gestures[0]["id"])
        if name in {t.name for t in tools}:
            name = f"{kind.lower()}_{_snake(gestures[0]['id'])}"
        description = f"Geste Domia ({kind}) : {'; '.join(lines)}. Joué au nom de la personne qui parle."

        def run(args: dict, who: Speaker, path=path, method=method, in_body=in_body, gestures=gestures) -> Any:
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

        def house_wide(args: dict, kind=kind) -> bool:
            return kind == "HOUSE" and args.get("value") in HOUSE_WIDE_SITUATIONS

        tools.append(Tool(name, description, obj(props, required), run, gesture=True, house_wide=house_wide))
    return tools


def _snake(name: str) -> str:
    return re.sub(r"(?<!^)([A-Z])", r"_\1", name).lower()


def read_tools(domia: Domia, zone: str = "Europe/Zurich") -> list[Tool]:
    """Savoir la maison (spec de l'assistant complet §4) : chaque lecture vise (pièce, sorte, objet, période)."""
    tz = ZoneInfo(zone)

    def settings() -> reading.Settings:
        return reading.Settings(domia.config())

    def house(args: dict, who: Speaker) -> Any:
        raw = domia.house()
        return reading.house_view(raw, compact_house(raw), args.get("room"), args.get("kind"))

    def facts(args: dict, who: Speaker) -> Any:
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

    def nights(args: dict, who: Speaker) -> Any:
        """Les changements de situation, en heure locale : en quelques lignes ce que le journal dit en milliers de jetons."""
        today = datetime.now(tz).date()
        days = min(max(int(args.get("days", 7)), 1), 31)
        lines = domia.memory((today - timedelta(days=days - 1)).isoformat(), today.isoformat())
        return reading.situations(lines, tz) or "aucun changement de situation ces jours-là"

    def activity(args: dict, who: Speaker, limit: int = 12) -> Any:
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

    def why(args: dict, who: Speaker) -> Any:
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

    def read_settings(args: dict, who: Speaker) -> Any:
        s = settings()
        kind = args.get("kind")
        if not kind:
            return s.index()
        out = s.entry(kind, args.get("id"))
        out["revision"] = s.revision
        if args.get("explain"):
            out["aide"] = reading.explain(kind, args.get("field"))
        return out

    def status(args: dict, who: Speaker) -> Any:
        return reading.health_view(domia.health(), domia.memory_summary())

    def notifications(args: dict, who: Speaker) -> Any:
        out: dict[str, Any] = {
            "envoyées": reading.notification_view(domia.notifications(), tz, min(max(int(args.get("days", 7)), 1), 30))
        }
        if args.get("services"):
            out["services"] = domia.notify_services()
        return out

    def estimates(args: dict, who: Speaker) -> Any:
        models = settings().config.get("estimates") or []
        now = domia.facts().get("estimates") or {}

        def current(id: str) -> dict:
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

    def ha(args: dict, who: Speaker) -> Any:
        return reading.ha_view(domia.ha_entities(), settings().entities(), args.get("domain"), bool(args.get("unused")))

    def test_notification(args: dict, who: Speaker) -> Any:
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


NAMEPLATE = "Lis cette plaque signalétique ou cette facture. Rends en JSON : brand, model, serial, et si visibles bought_at, shop, price_chf. Rien d'inventé : null si illisible."
MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".heic": "image/heic"}


def library_tools(library: Library, look: Callable[[bytes, str, str], str] | None = None) -> list[Tool]:
    def search(args: dict, who: Speaker) -> Any:
        return [{"source": p.cite(), "text": p.text} for p in library.search(args["question"], int(args.get("k", 5)))]

    def photo(args: dict, who: Speaker) -> Any:
        path = next((p for p in library.inbox() if p.name == args["file"]), None)
        if look is None or path is None or path.suffix.lower() not in MIME:
            return {"error": "photo introuvable dans à-trier"}
        return {"file": path.name, "read": look(path.read_bytes(), MIME[path.suffix.lower()], NAMEPLATE)}

    def card(args: dict, who: Speaker) -> Any:
        found = library.card(args["id"])
        return found if found is not None else {"error": "fiche inconnue", "cards": sorted(library.cards())}

    return [
        Tool(
            "search_library",
            "Cherche dans les manuels, factures et documents du foyer ; rend les passages avec leur source et page. Toujours citer la source.",
            obj({"question": {"type": "string"}, "k": {"type": "integer", "minimum": 1, "maximum": 10}}, ["question"]),
            search,
        ),
        Tool(
            "list_cards",
            "Les fiches des objets du ménage (id et nom).",
            obj({}),
            lambda a, w: {k: v.get("name", k) for k, v in library.cards().items()},
        ),
        Tool(
            "object_card",
            "La fiche d'un objet : marque, modèle, achat, garantie, entretien, pièces, documents.",
            obj({"id": {"type": "string"}}, ["id"]),
            card,
        ),
        Tool(
            "update_card",
            "Crée ou complète la fiche d'un objet (champs : name, room, brand, model, serial, bought_at, shop, price_chf, warranty_until, domia, maintenance, parts, documents, notes).",
            obj({"id": {"type": "string"}, "fields": {"type": "object"}}, ["id", "fields"]),
            lambda a, w: library.save_card(a["id"], a["fields"]),
        ),
        Tool(
            "maintenance_due",
            "Les tâches d'entretien des objets dont l'échéance est passée.",
            obj({}),
            lambda a, w: library.maintenance_due(datetime.now().date()),
        ),
        Tool(
            "inbox",
            "Les photos et documents déposés dans « à-trier » (inventaire en photos).",
            obj({}),
            lambda a, w: [p.name for p in library.inbox()],
        ),
    ] + (
        [
            Tool(
                "read_photo",
                "Lit une photo de « à-trier » (plaque signalétique, facture) : marque, modèle, numéro de série. Ensuite, créer la fiche et ne demander que ce qui manque.",
                obj({"file": {"type": "string"}}, ["file"]),
                photo,
            )
        ]
        if look
        else []
    )


def settings_tools(domia: Domia, memory: Memory) -> list[Tool]:
    """Régler avec un Oui (spec de l'assistant complet §5) : proposer, puis appliquer après le oui, ou annuler."""
    settler = Settler(domia, memory)
    kinds = sorted(NOUNS)
    change = {
        "type": "object",
        "properties": {
            "op": {"type": "string", "enum": ["set", "add", "remove"]},
            "kind": {"type": "string", "enum": kinds},
            "id": {
                "type": "string",
                "description": "l'objet (set, remove) ; rien pour house, notifications, situation_changes",
            },
            "room": {"type": "string", "description": "la pièce d'un objet ajouté (add)"},
            "fields": {
                "type": "object",
                "description": "les champs de la config (noms de settings, délais en secondes, « a.b » pour un champ imbriqué, null retire) ; jamais d'id à l'ajout",
            },
        },
        "required": ["op", "kind"],
    }
    return [
        Tool(
            "propose_settings",
            "Propose de changer des réglages de Domia : Domia vérifie sans rien écrire, puis je demande son oui à la personne. Lis d'abord l'objet avec settings.",
            obj({"changes": {"type": "array", "items": change}}, ["changes"]),
            lambda a, w: settler.propose(a["changes"], w.person),
        ),
        Tool(
            "apply_settings",
            "Applique une proposition de réglage, seulement après le oui de la personne.",
            obj({"proposal": {"type": "integer"}}, ["proposal"]),
            lambda a, w: settler.apply(a["proposal"], w.person),
            gesture=True,
            house_wide=lambda a: True,
        ),
        Tool(
            "undo_settings",
            "Propose d'annuler le dernier réglage fait par l'assistant pour cette personne (« annule »).",
            obj({}),
            lambda a, w: settler.undo(w.person),
        ),
    ]


def memory_tools(memory: Memory) -> list[Tool]:
    def remember(args: dict, who: Speaker) -> Any:
        personal = bool(args.get("personal"))
        if personal and not who.person:
            return {"error": "une note personnelle a besoin de savoir qui parle"}
        return {"id": memory.remember(args["fact"], who.person, personal)}

    def forget(args: dict, who: Speaker) -> Any:
        return {"forgotten": memory.forget(int(args["id"]), who.person)}

    return [
        Tool(
            "remember",
            "Retient une note du foyer (« les ampoules E14 sont dans le placard de l'entrée ») ou une préférence personnelle de la personne qui parle (personal: true).",
            obj({"fact": {"type": "string"}, "personal": {"type": "boolean"}}, ["fact"]),
            remember,
        ),
        Tool(
            "recall",
            "Retrouve les notes du foyer (et celles de la personne qui parle) liées à une question.",
            obj({"question": {"type": "string"}}, ["question"]),
            lambda a, w: memory.recall(a["question"], w.person),
        ),
        Tool(
            "what_you_know_about_me",
            "Ce que l'assistant sait de la personne qui parle.",
            obj({}),
            lambda a, w: memory.about(w.person) if w.person else [],
        ),
        Tool(
            "forget",
            "Oublie une note par son id (une note du foyer, ou une note de la personne qui parle).",
            obj({"id": {"type": "integer"}}, ["id"]),
            forget,
        ),
        Tool(
            "not_now",
            "La personne ne veut plus entendre parler de ce sujet pour l'instant (un constat, une remarque) : il se tait une semaine, puis plus longtemps.",
            obj({"subject": {"type": "string"}}, ["subject"]),
            lambda a, w: {"quiet_until": memory.refuse(a["subject"], datetime.now(UTC)).isoformat()},
        ),
    ]


def agenda_tools(agenda: Agenda) -> list[Tool]:
    def guarded(fn: Callable[[dict, Speaker], Any]) -> Callable[[dict, Speaker], Any]:
        def run(args: dict, who: Speaker) -> Any:
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

    def search(args: dict, who: Speaker) -> Any:
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

    def tomorrow(args: dict, who: Speaker) -> Any:
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

    def accept(args: dict, who: Speaker) -> Any:
        done = engagements.accept(args.get("id"), who.person, datetime.now(UTC))
        return (
            {"accepted": [e["question"] for e in done]}
            if done
            else {"error": "aucune proposition en attente avec cet id"}
        )

    def cancel(args: dict, who: Speaker) -> Any:
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


# Les types de demande du modèle en deux temps (spec de l'assistant complet §16.12) : le premier appel en choisit un ou
# deux, le second ne voit que leurs outils. Un outil hors de son type reste jouable si le modèle l'appelle quand même.
FAMILIES = {
    "gestes": "agir maintenant sur la maison : lumières, appareils, volets, chauffage, robots, Jour, Nuit, Absent",
    "maison": "savoir ce qui se passe ou s'est passé : état, températures, pourquoi, historique, constats, présence",
    "réglages": "lire ou changer un réglage durable (délai, seuil, loi, notification), la santé de Domia, Home Assistant",
    "bibliothèque": "une panne, un manuel, une garantie, un entretien, le logement, une fiche d'objet, le web",
    "mémoire": "retenir ou retrouver une note, où une chose est rangée, ce que tu sais de moi",
    "agenda": "rappels, liste de courses, calendrier",
    "demain": "la météo, le plan de demain, ce qui est prévu, oui ou non à une proposition",
}


def _families(table: dict[str, list[str]]) -> dict[str, frozenset[str]]:
    out: dict[str, set[str]] = {}
    for family, names in table.items():
        for name in names:
            out.setdefault(name, set()).add(family)
    return {name: frozenset(families) for name, families in out.items()}


FAMILY_OF = _families(
    {
        "gestes": ["house", "set_situation"],
        "maison": ["house", "facts", "activity", "why", "situations", "observations", "estimates", "habits"],
        "réglages": [
            "settings",
            "propose_settings",
            "apply_settings",
            "undo_settings",
            "system_status",
            "notifications",
            "ha_entities",
            "test_notification",
        ],
        "bibliothèque": [
            "search_library",
            "list_cards",
            "object_card",
            "update_card",
            "maintenance_due",
            "inbox",
            "read_photo",
            "web_search",
            "recall",
        ],
        "mémoire": ["remember", "recall", "what_you_know_about_me", "forget", "not_now"],
        "agenda": ["reminders", "add_reminder", "complete_reminder", "calendar", "add_event"],
        # oui ou non à une proposition (une situation, un plan) : pas un geste sur la maison ; au banc, « on part pour le
        # week-end » acceptait une proposition au lieu de passer en Absent
        "demain": [
            "weather",
            "habits",
            "plan_tomorrow",
            "planned",
            "accept_planned",
            "cancel_planned",
            "accept_proposal",
            "refuse_proposal",
        ],
    }
)


class Toolbox:
    def __init__(
        self,
        tools: list[Tool],
        families: dict[str, str] | None = None,
        notes: str = "",
        owner: Speaker | None = None,
    ):
        self.tools = {t.name: t for t in tools}
        self.extra = families or {}  # les domaines du hub, en plus des types de la maison
        self.notes = notes  # leurs consignes, pour qui atteint leurs outils
        self.owner = owner  # une personne qui les atteint (le préchauffage de son préfixe)

    def families(self, who: Speaker | None = None) -> dict[str, str]:
        """Les types de demande que le routeur peut nommer pour cette personne."""
        seen = {f for t in self.tools.values() if t.family and t.allowed(who) for f in t.families}
        return {**FAMILIES, **{name: what for name, what in self.extra.items() if name in seen}}

    def schemas(self, families: frozenset[str] | None = None, who: Speaker | None = None) -> list[dict]:
        """Les outils montrés au modèle : tous, ou ceux de ces types de demande ; jamais un outil que la personne
        n'atteint pas (les outils du hub, pour Kim)."""
        return [
            t.schema() for t in self.tools.values() if t.allowed(who) and (families is None or t.families & families)
        ]

    def system_notes(self, who: Speaker | None) -> str:
        return self.notes if any(t.family and t.allowed(who) for t in self.tools.values()) else ""

    def get(self, name: str) -> Tool | None:
        return self.tools.get(name)

    def run(self, name: str, args: dict, who: Speaker) -> Any:
        tool = self.tools.get(name)
        if tool is None or not tool.allowed(who):
            return {"error": f"outil inconnu : {name}"}
        try:
            result = tool.run(args, who)
            return result if tool.gesture else reading.fit(result)
        except DomiaError as e:
            return {"error": str(e)}
        except (KeyError, ValueError, TypeError, AttributeError) as e:  # au banc : une pièce donnée en objet
            return {"error": f"arguments invalides : {e}"}


def build(
    domia: Domia,
    library: Library | None,
    memory: Memory | None,
    agenda: Agenda | None,
    searx_url: str | None = None,
    look: Callable[[bytes, str, str], str] | None = None,
    zone: str = "Europe/Zurich",
    plan: Callable[[datetime, Any], Any] | None = None,
    engagements: Any | None = None,
    settings_write: bool = False,
    hub: Any | None = None,
) -> Toolbox:
    """Tous les outils, les gestes relus du catalogue et de la maison du moment."""
    house = domia.house()
    tools = (
        read_tools(domia, zone)
        + gesture_tools(domia.catalog(), house, domia)
        + planning_tools(domia, plan, engagements, zone)
    )
    if library:
        tools += library_tools(library, look)
    if memory:
        tools += memory_tools(memory) + (settings_tools(domia, memory) if settings_write else [])
    if agenda:
        tools += agenda_tools(agenda)
    tools += web_tools(searx_url)
    if hub is not None:  # domia_assistant.hub.HubModule
        return Toolbox(tools + hub.tools, hub.families, hub.notes, hub.owner)
    return Toolbox(tools)
