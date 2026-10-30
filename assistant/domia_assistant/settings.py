"""Régler avec un Oui (spec de l'assistant complet §5) : le modèle décrit des changements typés, jamais la config
entière ; l'assistant les pose sur sa copie de `GET /api/config`, Domia les vérifie sans rien écrire
(`POST /api/config/preview`), la personne voit un résumé en unités de l'écran et dit oui, puis l'écriture part avec
`If-Match` sur la révision lue. Chaque réglage appliqué garde son inverse : « annule » le repropose, avec un Oui.

Le Oui ne passe jamais par le modèle : la boucle pose la question elle-même et ne joue `apply_settings` qu'à la phrase
suivante de la même personne (`Assistant._ask`) ; le MCP exige `confirmed: true`, comme un geste de toute la maison."""

from __future__ import annotations

import copy
from datetime import UTC, datetime, timedelta
from typing import Any

from .domia import Domia
from .memory import Memory
from .reading import KINDS, LISTED, SINGLE

PROPOSAL_TTL = timedelta(minutes=15)
NOUNS = {
    "light": "lampe",
    "sensor": "capteur",
    "appliance": "appareil",
    "cover": "volet",
    "emitter": "émetteur",
    "machine": "robot",
    "room": "pièce",
    "button": "bouton",
    "binding": "liaison",
    "person": "personne",
    "estimate": "estimation",
    "house": "maison",
    "notifications": "notifications",
    "situation_changes": "changements de situation",
}


def human(value: Any, field: str) -> str:
    """Une valeur comme l'écran la montre : les délais en minutes ou en heures, oui/non, « rien »."""
    if value is None:
        return "rien"
    if isinstance(value, bool):
        return "oui" if value else "non"
    if field.endswith("_sec") and isinstance(value, (int, float)):
        seconds = int(value)
        if seconds and seconds % 3600 == 0:
            return f"{seconds // 3600} h"
        if seconds >= 60 and seconds % 60 == 0:
            return f"{seconds // 60} min"
        return f"{seconds} s"
    if isinstance(value, (dict, list)):
        return str(value).replace("'", "")
    return str(value)


def _get(obj: dict, path: str) -> Any:
    value: Any = obj
    for part in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def _put(obj: dict, path: str, value: Any) -> None:
    parts = path.split(".")
    for part in parts[:-1]:
        obj = obj.setdefault(part, {})
    if value is None:
        obj.pop(parts[-1], None)
    else:
        obj[parts[-1]] = value


class Draft:
    """La copie de la config que les changements modifient, avec son résumé et l'inverse de chaque changement."""

    def __init__(self, config: dict):
        self.config = copy.deepcopy(config)
        self.rooms_before = _rooms(config)  # la pièce de chaque objet : l'inverse d'un retrait l'y remet
        self.summary: list[str] = []
        self.undo: list[dict] = []

    def _find(self, kind: str, id: str | None) -> tuple[list, dict, str]:
        """La liste qui porte l'objet, l'objet, et son nom lisible (« Couloir › Plafonnier »)."""
        if kind in KINDS:
            for room in self.config.get("rooms") or []:
                for o in room.get(KINDS[kind]) or []:
                    if o.get("id") == id:
                        return room[KINDS[kind]], o, f"{room.get('name') or room['id']} › {o.get('name') or id}"
        elif kind in LISTED:
            items = self.config.get(LISTED[kind]) or []
            for o in items:
                if o.get("id") == id:
                    return items, o, str(o.get("name") or id)
        else:
            raise ValueError(f"sorte inconnue : {kind}")
        raise ValueError(f"aucun {kind} d'id {id} : lis l'index avec settings")

    def change(self, c: dict) -> None:
        op, kind, fields = c.get("op"), c.get("kind"), c.get("fields") or {}
        if kind not in NOUNS:
            raise ValueError(f"sorte inconnue : {kind}")
        if op == "set":
            if kind in SINGLE:
                target, label = self.config.get(kind) or {}, NOUNS[kind]
                self.config[kind] = target
            else:
                _, target, label = self._find(kind, c.get("id"))
            if not fields:
                raise ValueError("set sans fields")
            before = {}
            for field, value in fields.items():
                if field == "id":
                    raise ValueError("l'id d'un objet ne change pas")
                was = _get(target, field)
                if was == value:
                    continue  # « auto_off oui → oui » n'est pas un changement
                before[field] = copy.deepcopy(was)
                _put(target, field, value)
                self.summary.append(f"{label} : {field} {human(before[field], field)} → {human(value, field)}")
            if not before:
                raise ValueError("rien ne change : ces champs ont déjà ces valeurs")
            self.undo.append({"op": "set", "kind": kind, "id": c.get("id"), "fields": before})
        elif op == "add":
            if "id" in fields:
                raise ValueError("un objet neuf part sans id : Domia le donne")
            if kind in KINDS:
                room = next((r for r in self.config.get("rooms") or [] if r.get("id") == c.get("room")), None)
                if room is None:
                    raise ValueError(f"ajouter un {kind} demande sa pièce (room), une pièce existante")
                room.setdefault(KINDS[kind], []).append(copy.deepcopy(fields))
                where = f" dans {room.get('name') or room['id']}"
            elif kind in LISTED:
                self.config.setdefault(LISTED[kind], []).append(copy.deepcopy(fields))
                where = ""
            else:
                raise ValueError(f"on n'ajoute pas de {kind}")
            self.summary.append(
                f"ajout : {NOUNS[kind]} « {fields.get('name') or fields.get('ha_entity_id') or '?'} »{where}"
            )
            self.undo.append({"op": "remove-new", "kind": kind, "fields": fields})
        elif op == "remove":
            items, target, label = self._find(kind, c.get("id"))
            items.remove(target)
            self.summary.append(f"retrait : {NOUNS[kind]} {label}")
            fields = {k: v for k, v in target.items() if k != "id"}
            self.undo.append(
                {"op": "add", "kind": kind, "room": self.rooms_before.get((kind, str(c.get("id")))), "fields": fields}
            )
        else:
            raise ValueError(f"op inconnue : {op} (set, add, remove)")


def _rooms(config: dict) -> dict[tuple[str, str], str]:
    return {
        (k, str(o.get("id"))): r["id"]
        for r in config.get("rooms") or []
        for k, p in KINDS.items()
        for o in r.get(p) or []
    }


def _ids(config: dict, kind: str) -> set[str]:
    if kind in KINDS:
        return {o.get("id") for r in config.get("rooms") or [] for o in r.get(KINDS[kind]) or []}
    return {o.get("id") for o in config.get(LISTED.get(kind, ""), []) or []}


class Settler:
    """Proposer, appliquer, annuler : la mémoire garde chaque proposition (15 minutes) et l'inverse de chaque réglage."""

    def __init__(self, domia: Domia, memory: Memory, now=lambda: datetime.now(UTC)):
        self.domia = domia
        self.memory = memory
        self.now = now

    def propose(self, changes: list[dict], who: str | None, undoes: int | None = None) -> dict:
        read = self.domia.config()
        draft = Draft(read["config"])
        if not changes:
            raise ValueError("aucun changement")
        for c in changes:
            draft.change(c)
        checked = self.domia.config_preview(draft.config, read["config_revision"])
        if not checked.get("valid"):
            return {
                "error": "Domia refuse ce réglage",
                "messages": [f"{m.get('path')} : {m.get('message')}" for m in checked.get("messages") or []],
            }
        removed = {k: v for k, v in (checked.get("removed") or {}).items() if v}
        id = self.memory.propose_settings(
            who, read["config_revision"], changes, draft.undo, draft.summary, self.now(), undoes
        )
        warnings = [m.get("message") for m in checked.get("warnings") or []]
        return {
            "proposition": id,
            "résumé": draft.summary,
            "avertissements": warnings,
            "retirés": removed,
            "question": "Je change ceci : "
            + " ; ".join(draft.summary)
            + (f" (retirés aussi : {removed})" if removed else "")
            + ". Domia l'accepte. Je l'applique ?",
        }

    def apply(self, proposal: int, who: str | None) -> dict:
        row = self.memory.settings_change(int(proposal))
        if row is None or row["state"] != "PROPOSED" or row["person"] != who:
            return {"error": "pas de proposition en attente sous ce numéro, pour cette personne"}
        if self.now() - datetime.fromisoformat(row["at"]) > PROPOSAL_TTL:
            return {"error": "proposition trop ancienne (15 min) : refais-la"}
        read = self.domia.config()
        if read["config_revision"] != row["revision"]:
            return {"error": "la configuration a changé depuis la proposition (à l'écran ?) : refais-la"}
        draft = Draft(read["config"])
        for c in row["changes"]:
            draft.change(c)
        before = {k: _ids(read["config"], k) for k in {u["kind"] for u in row["undo"]}}
        self.domia.config_put(draft.config, row["revision"], who)
        after = self.domia.config()["config"]
        self.memory.settings_applied(row["id"], [self._resolve(u, before, after) for u in row["undo"]], self.now())
        if row["undoes"]:
            self.memory.settings_undone_by(row["undoes"], row["id"])
        return {"appliqué": row["summary"]}

    @staticmethod
    def _resolve(undo: dict, before: dict, after: dict) -> dict:
        """L'inverse d'un ajout : retirer l'objet que Domia vient de créer, dont l'id n'est connu qu'après."""
        if undo["op"] != "remove-new":
            return undo
        fresh = sorted(_ids(after, undo["kind"]) - before.get(undo["kind"], set()))
        return {"op": "remove", "kind": undo["kind"], "id": fresh[0]} if fresh else {"op": "noop"}

    def undo(self, who: str | None) -> dict:
        row = self.memory.last_applied_settings(who)
        if row is None:
            return {"error": "aucun réglage de l'assistant à annuler"}
        changes = [c for c in reversed(row["undo"]) if c["op"] != "noop"]
        return self.propose(changes, who, undoes=row["id"])
