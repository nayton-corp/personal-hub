"""Le socle des outils (spec §7) : qui parle (`Speaker`), un outil (`Tool`, son schéma, ses familles), et la
maison compactée pour le modèle. Les familles d'outils sont dans tools_house, tools_knowledge, tools_agenda ;
`tools` les assemble."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

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
    parameters: dict[str, Any]
    run: Callable[[dict[str, Any], Speaker], Any]
    gesture: bool = False
    house_wide: Callable[[dict[str, Any]], bool] = field(default=lambda args: False)
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

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {"name": self.name, "description": self.description, "parameters": self.parameters},
        }


def obj(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required or [], "additionalProperties": False}


def compact_house(house: dict[str, Any]) -> dict[str, Any]:
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


def field_schema(spec: dict[str, Any]) -> dict[str, Any]:
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


def snake(name: str) -> str:
    return re.sub(r"(?<!^)([A-Z])", r"_\1", name).lower()


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
