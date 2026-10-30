"""Savoir la maison (spec de l'assistant complet §2, §4) : des lectures ciblées par intention, jamais un état complet.
Chaque outil prend de quoi viser (pièce, sorte, objet, période), ne rend que les champs utiles, et `fit` coupe proprement
ce qui dépasse le plafond d'une réponse (BUDGET_CHARS) en disant comment affiner. Le journal (48 h) se lit en agrégats,
la mémoire longue (90 jours) en changements de situation."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

# Le plafond d'une réponse d'outil : environ 800 à 1 000 jetons, ce que la boucle du modèle garde d'un résultat.
BUDGET_CHARS = 3000
SITUATION_FR = {"DAY": "Jour", "NIGHT": "Nuit", "AWAY": "Absent"}
DAYS_FR = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
OBJECT_KINDS = ("lights", "sensors", "appliances", "covers", "emitters", "machines")
KINDS = {
    "light": "lights",
    "sensor": "sensors",
    "appliance": "appliances",
    "cover": "covers",
    "emitter": "emitters",
    "machine": "machines",
}
SINGLE = ("house", "notifications", "situation_changes")
LISTED = {"room": "rooms", "button": "buttons", "binding": "bindings", "person": "people", "estimate": "estimates"}
# La section de config-reference.md qui explique chaque sorte (spec §4, `explain`).
HELP_SECTION = {
    "house": "## 3.",
    "room": "### 4.1",
    "light": "### 4.2",
    "sensor": "### 4.4",
    "appliance": "### 4.5",
    "cover": "### 4.7",
    "machine": "### 4.8",
    "emitter": "### 4.9",
    "button": "## 5.",
    "binding": "## 6.",
    "notifications": "## 13.",
    "person": "### 14.1",
    "situation_changes": "### 14.2",
    "estimate": "## 15.",
}
OLDEST_FIRST = {"gestes", "envoyées", "items", "lines"}
REFERENCE = Path(__file__).resolve().parent / "contract" / "config-reference.md"


def size(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, default=str))


def fit(value: Any, budget: int = BUDGET_CHARS) -> Any:
    """La réponse sous le plafond : une liste perd ses plus vieux éléments, un objet raccourcit sa plus longue liste,
    un texte est coupé. Ce qui est coupé est dit, avec la façon d'affiner."""
    if size(value) <= budget:
        return value
    if isinstance(value, list):
        kept = list(value)
        while kept and size(kept) > budget - 160:
            kept.pop(0)
        return {
            "items": kept,
            "tronqué": f"les {len(kept)} derniers sur {len(value)} : affine (pièce, sorte, objet, période)",
        }
    if isinstance(value, dict):
        out = dict(value)
        lists = [k for k, v in out.items() if isinstance(v, (list, dict)) and v]
        while size(out) > budget and lists:
            key = max(lists, key=lambda k: size(out[k]))
            if len(out[key]) <= 1:
                lists.remove(key)
                continue
            if isinstance(out[key], dict):
                keys = list(out[key])
                out[key] = {k: out[key][k] for k in keys[: len(keys) // 2]}
                out["tronqué"] = f"{key} raccourci : affine (pièce, sorte, objet, sujet)"
                continue
            # une liste dans l'ordre du temps perd son début (le plus vieux), une autre sa fin
            half = len(out[key]) // 2
            out[key] = out[key][half:] if key in OLDEST_FIRST else out[key][:half]
            out["tronqué"] = "réponse raccourcie : affine (pièce, sorte, objet, période)"
        if size(out) <= budget:
            return out
        value = json.dumps(out, ensure_ascii=False, default=str)
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    return text[: budget - 40] + " … (tronqué : affine la question)"


def _match(wanted: str | None, *names: Any) -> bool:
    if not wanted:
        return True
    w = wanted.strip().lower()
    return any(n is not None and (str(n).lower() == w or w in str(n).lower()) for n in names)


def house_view(house: dict, compact: dict, room: str | None = None, kind: str | None = None) -> dict:
    """La maison en court (`compact`), réduite à une pièce (id ou nom) et à une sorte d'objets."""
    rooms = [r for r in compact["rooms"] if _match(room, r["id"], r.get("name"))]
    out: dict[str, Any] = {"situation": compact["situation"]}
    plural = KINDS.get(kind or "", kind)
    if plural in ("machines", "people"):
        out[plural] = compact[plural]
        return out
    if plural:
        rooms = [{"id": r["id"], "name": r.get("name"), plural: r.get(plural, [])} for r in rooms if r.get(plural)]
    out["rooms"] = rooms
    if not room and not kind:
        out["machines"] = compact["machines"]
        out["people"] = compact["people"]
    return out


class Settings:
    """Les réglages lus dans `GET /api/config` : un index court, puis la fiche d'un objet."""

    def __init__(self, document: dict):
        self.revision = document.get("config_revision")
        self.config = document.get("config") or {}

    def index(self) -> dict:
        rooms = []
        for r in self.config.get("rooms") or []:
            room: dict[str, Any] = {"id": r["id"], "name": r.get("name")}
            for plural in OBJECT_KINDS:
                items = [[o.get("id"), o.get("name")] for o in r.get(plural) or []]
                if items:
                    room[plural] = items
            rooms.append(room)
        return {
            "revision": self.revision,
            "house": self.config.get("house"),
            "rooms": rooms,
            "buttons": [[b.get("id"), b.get("name")] for b in self.config.get("buttons") or []],
            "bindings": len(self.config.get("bindings") or []),
            "people": [[p.get("id"), p.get("name")] for p in self.config.get("people") or []],
            "estimates": [[e.get("id"), e.get("kind")] for e in self.config.get("estimates") or []],
            "aussi": "notifications, situation_changes",
        }

    def entry(self, kind: str, id: str | None) -> dict:
        if kind in SINGLE:
            return {"kind": kind, "settings": self.config.get(kind)}
        if kind in LISTED:
            items = self.config.get(LISTED[kind]) or []
            if kind == "binding" and id is None:
                return {"kind": kind, "settings": items}
            found = [o for o in items if o.get("id") == id]
            if kind == "room" and found:
                room = {k: v for k, v in found[0].items() if k not in OBJECT_KINDS and k != "space"}
                room.update({p: [o.get("id") for o in found[0].get(p) or []] for p in OBJECT_KINDS if found[0].get(p)})
                return {"kind": kind, "id": id, "settings": room}
            if found:
                return {"kind": kind, "id": id, "settings": found[0]}
        elif kind in KINDS:
            for r in self.config.get("rooms") or []:
                for o in r.get(KINDS[kind]) or []:
                    if o.get("id") == id:
                        # la place dans la 3D se pose à l'écran (spec §7) : elle n'aide pas une phrase
                        return {
                            "kind": kind,
                            "id": id,
                            "room": r["id"],
                            "settings": {k: v for k, v in o.items() if k != "place"},
                        }
        else:
            raise ValueError(f"sorte inconnue : {kind}")
        raise ValueError(f"aucun {kind} d'id {id} : appelle settings sans argument pour l'index")

    def entities(self) -> set[str]:
        """Les entités HA que la config nomme quelque part."""
        return set(re.findall(r'"([a-z_]+\.[a-z0-9_]+)"', json.dumps(self.config)))


def explain(kind: str, field: str | None = None, path: Path = REFERENCE) -> str:
    """La section de config-reference.md pour cette sorte ; avec un champ, ses seules lignes."""
    if not path.exists():
        return "la référence des réglages n'est pas sur cette machine"
    head = HELP_SECTION.get(kind)
    if head is None:
        return f"pas d'aide pour {kind}"
    lines = path.read_text(encoding="utf-8").splitlines()
    start = next((i for i, line in enumerate(lines) if line.startswith(head)), None)
    if start is None:
        return f"pas d'aide pour {kind}"
    end = next(
        (
            i
            for i in range(start + 1, len(lines))
            if lines[i].startswith("## ") or (lines[i].startswith("### ") and head.startswith("### "))
        ),
        len(lines),
    )
    section = lines[start:end]
    if field:
        hits = [line for line in section if f"`{field}`" in line]
        section = section[:1] + (hits or [f"(le champ {field} n'est pas décrit ici)"])
    return "\n".join(section)


def _local(at: str, tz: ZoneInfo) -> str:
    when = datetime.fromisoformat(at.replace("Z", "+00:00")).astimezone(tz)
    return f"{DAYS_FR[when.weekday()]} {when:%d.%m %H:%M}"


def situations(lines: list[dict], tz: ZoneInfo) -> list[str]:
    out = []
    for line in lines:
        if line.get("kind") != "situation":
            continue
        out.append(
            f"{_local(line['at'], tz)} {SITUATION_FR.get(line['from'], line['from'])} → {SITUATION_FR.get(line['to'], line['to'])} ({line.get('origin', '?')})"
        )
    return out


def activity(
    lines: list[dict], tz: ZoneInfo, entities: dict[str, str], wanted: set[str] | None = None, limit: int = 12
) -> dict:
    """Le journal en agrégats : les gestes (qui, quoi, quand) et, par entité, combien de changements, le dernier état
    et son heure. Les points de reprise et les tops d'horloge sont ignorés. `entities` : entité HA → id Domia ;
    `wanted` : les ids d'objets et entités à garder (None : tout)."""
    commands: list[dict[str, Any]] = []
    changes: dict[str, dict[str, Any]] = {}
    estimated: dict[str, Any] = {}  # par estimation, la dernière valeur envoyée : seul un changement est un geste
    for line in lines:
        kind = line.get("type")
        if kind == "command":
            c = line.get("command") or {}
            args = c.get("args") or {}
            target = next((str(v) for k, v in args.items() if k.endswith("_id") and v), None)
            if wanted is not None and target not in wanted:
                continue
            if c.get("name") == "ReportEstimate" and target is not None:  # le radar envoie toutes les 30 s
                if target in estimated and estimated[target] == args.get("value"):
                    continue
                estimated[target] = args.get("value")
            item = {
                "at": _local(line["at"], tz) if line.get("at") else None,
                "geste": c.get("name"),
                "origine": c.get("origin"),
            }
            item.update({k: v for k, v in args.items() if v is not None})
            if c.get("on_behalf_of") or c.get("person"):
                item["pour"] = c.get("on_behalf_of") or c.get("person")
            commands.append(item)
        elif kind == "entity_change":
            e = line.get("entity_change") or {}
            entity = e.get("entity_id")
            if not entity or (wanted is not None and entity not in wanted and entities.get(entity) not in wanted):
                continue
            seen = changes.setdefault(entity, {"entité": entity, "objet": entities.get(entity), "changements": 0})
            seen["changements"] += 1
            seen["état"] = (e.get("new_state") or {}).get("state")
            if line.get("at"):
                seen["à"] = _local(line["at"], tz)
                seen["_at"] = line["at"]
    ordered = sorted(changes.values(), key=lambda c: c.get("_at", ""), reverse=True)
    for c in ordered:
        c.pop("_at", None)
        if c["objet"] is None:
            c.pop("objet")
    return {
        "gestes": commands[-limit:],
        "changements": ordered[:limit],
        "gestes_en_tout": len(commands),
        "entités_en_tout": len(ordered),
    }


def health_view(health: dict, summary: dict | None) -> dict:
    out = {
        k: health.get(k)
        for k in ("status", "ha", "ha_link", "started_at", "loop_last_cycle_at")
        if health.get(k) is not None
    }
    out["version"] = (health.get("build") or {}).get("version")
    out["disque"] = "ok" if (health.get("persist") or {}).get("ok") else (health.get("persist") or {}).get("last_error")
    out["alertes"] = [
        {"code": w.get("code"), "combien": len(w.get("details") or []) or None, "message": w.get("message")}
        for w in health.get("warnings") or []
    ]
    missing = (health.get("snapshot") or {}).get("missing_entity_ids") or []
    if missing:
        out["entités_manquantes"] = missing
    if summary is not None:
        out["mémoire"] = {k: summary.get(k) for k in ("since", "days", "gaps") if summary.get(k) is not None}
    return out


def notification_view(entries: list[dict], tz: ZoneInfo, days: int) -> list[dict]:
    since = datetime.now(UTC) - timedelta(days=days)
    out = []
    for n in entries:
        at = n.get("at")
        if at and datetime.fromisoformat(at.replace("Z", "+00:00")) < since:
            continue
        out.append(
            {
                k: v
                for k, v in {
                    "à": _local(at, tz) if at else None,
                    "titre": n.get("title"),
                    "message": n.get("message"),
                    "statut": n.get("status"),
                    "sorte": n.get("kind"),
                }.items()
                if v
            }
        )
    return out


def ha_view(entities: list[dict], used: set[str], domain: str | None, unused: bool) -> list[dict]:
    out = []
    for e in entities:
        if domain and e.get("domain") != domain:
            continue
        taken = e.get("entity_id") in used
        if unused and taken:
            continue
        item = {k: e.get(k) for k in ("entity_id", "name", "state", "device_class") if e.get(k) is not None}
        if not unused:
            item["dans_domia"] = taken
        out.append(item)
    return out


def recipients_for(config: dict, to: str | None, person: str | None) -> list[dict] | str:
    """Les destinataires de Réglages › Notifications que vise « à moi », « à Kim », « l'iPad de Robin » : Home
    Assistant liste souvent plusieurs services pour un même téléphone, le modèle n'a pas à deviner le bon. Sans `to`,
    la personne qui parle. Rend la liste visée, ou une phrase qui dit pourquoi personne."""
    recipients = (config.get("notifications") or {}).get("recipients") or []
    if not recipients:
        return "aucun destinataire dans Réglages › Notifications"
    if not to:
        to = next((p.get("name") for p in config.get("people") or [] if p.get("id") == person), None)
        if not to:
            return "je ne sais pas qui tu es : dis à qui l'envoyer"
    wanted = to.strip().lower().removeprefix("notify.")
    exact = [
        r
        for r in recipients
        if wanted in (str(r.get("id")).lower(), str(r.get("service")).lower().removeprefix("notify."))
    ]
    if exact:
        return exact
    words = [w for w in re.split(r"[\s'’_-]+", wanted) if w and w not in ("de", "du", "la", "le", "l", "à", "a")]
    found = [r for r in recipients if words and all(w in str(r.get("name") or r.get("id")).lower() for w in words)]
    return found or f"aucun destinataire ne correspond à « {to} »"
