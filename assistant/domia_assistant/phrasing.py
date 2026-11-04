"""Ce que l'assistant dit : la réponse (`reply`), l'inventaire de la maison pour le modèle, le compte rendu des
gestes joués ou manqués, les deux types de demande du routeur. Pas de réseau ici."""

from __future__ import annotations

import json
import logging
from typing import Any

from .tools import FAMILIES

LOG = logging.getLogger("assistant")


def router(catalog: dict[str, str]) -> dict[str, Any]:
    return {
        "role": "system",
        "content": "Tu ranges une demande faite à l'assistant d'une maison dans un ou deux types. "
        "Réponds seulement par leurs noms, séparés par une virgule, sans rien d'autre.\n"
        + "\n".join(f"{name} : {what}" for name, what in catalog.items()),
    }


ROUTER = router(FAMILIES)

# proposer ou annuler un réglage finit la phrase sur la question ; le oui suivant l'applique (spec de l'assistant complet §5)
SETTLERS = ("propose_settings", "undo_settings")
SETTLED = "C'est réglé. Dis « annule » si ça ne te va pas."
SITUATIONS = {"DAY": "Jour", "NIGHT": "Nuit", "AWAY": "Absent"}
KINDS = (("lights", "lampes"), ("appliances", "appareils"), ("covers", "volets/stores"), ("emitters", "chauffage/clim"))


def inventory(house: dict[str, Any]) -> list[str]:
    """Une ligne par pièce : ses objets, nom [id], par sorte ; puis les robots. Sans état : il vit dans `house`."""
    lines = []
    for room in house.get("rooms", []):
        kinds = []
        for key, label in KINDS:
            objects = room.get(key, []) or []
            if objects:
                kinds.append(f"{label} " + ", ".join(f"{o.get('name') or o['id']} [{o['id']}]" for o in objects))
        lines.append(
            f"- {room.get('name') or room['id']} [{room['id']}] : " + ("; ".join(kinds) or "rien de pilotable")
        )
    for m in house.get("machines", []) or []:
        lines.append(f"- robot {m.get('name') or m['id']} [{m['id']}]")
    return lines


# ce que fait chaque geste du catalogue, dit à la personne : le vocabulaire de Domia, pas des phrases à reconnaître
DID = {
    "TurnOn": "allumé",
    "TurnOff": "éteint",
    "TurnOnRoom": "allumée",
    "TurnOffRoom": "éteinte",
    "SetBrightness": "à {brightness_pct} %",
    "SetColor": "en {color}",
    "SetPosition": "à {position} %",
    "Open": "ouvert",
    "Close": "fermé",
    "Stop": "arrêté",
    "Release": "rendu à l'automatique",
    "SetSetpoint": "à {setpoint_c} °C",
    "SetMode": "en {mode}",
    "StartCleaning": "parti nettoyer",
    "Pause": "en pause",
    "Resume": "reparti",
    "ReturnToBase": "rentre à sa base",
    "Locate": "se signale",
    "StartProgram": "lancé",
}


def _names(house: dict[str, Any]) -> dict[str, str]:
    names = {}
    for room in house.get("rooms", []):
        names[room["id"]] = room.get("name") or room["id"]
        for key, _ in KINDS:
            for o in room.get(key, []) or []:
                names[o["id"]] = f"{names[room['id']]} › {o.get('name') or o['id']}"
    names.update({m["id"]: m.get("name") or m["id"] for m in house.get("machines", []) or []})
    return names


def _act(args: dict[str, Any], names: dict[str, str]) -> str:
    """Un geste dit d'après ce qui a été joué : l'objet, puis ce que le geste fait (« Couloir › Plafonnier éteint »)."""
    if "value" in args and "action" not in args:
        return f"maison en {SITUATIONS.get(args['value'], args['value'])}"
    action = args.get("action") or ""
    try:
        did = DID.get(action, action).format(**args)
    except (KeyError, IndexError):
        did = DID.get(action, action)
    return " ".join(p for p in (names.get(str(args.get("id") or ""), args.get("id")), did) if p)


def _told(acts: list[str], missed: list[str], said: str) -> str:
    """La réponse dit d'abord les gestes d'après leurs résultats, jamais d'après le texte du modèle (un geste joué ou
    raté se dit comme il s'est passé), puis ce que le modèle ajoute : une lecture demandée, une question."""
    parts = []
    if acts:
        parts.append("Fait : " + " ; ".join(acts) + ".")
    if missed:
        parts.append("Pas fait : " + " ; ".join(missed) + ".")
    if said:
        parts.append(said)
    return " ".join(parts) or "Je ne sais pas."


def reply(answer: str, done: list[str] | None = None) -> dict[str, Any]:
    return {"answer": answer, "done": list(done or []), "proposals": [], "confirm": None}


def _arguments(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    try:
        value = json.loads(raw or "{}")
        return value if isinstance(value, dict) else {}
    except ValueError:
        return {}


def _label(name: str, args: dict[str, Any]) -> str:
    if name == "apply_settings":
        return "réglage"
    parts = [args.get("action") or name, args.get("id"), args.get("value")]
    return " ".join(str(p) for p in parts if p)
