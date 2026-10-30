"""Un faux Domia en mémoire (spec §17) : la maison de test, le vrai catalogue figé côté backend, et les gestes reçus."""

import copy
import json
from pathlib import Path

from domia_assistant.domia import DomiaError
from tests.house import HOUSE

API = Path(__file__).resolve().parents[1] / "domia_assistant/contract/api"
GOLDEN = API / "catalog.golden.json"


def golden(name: str):
    return json.loads((API / name).read_text(encoding="utf-8"))


def catalog() -> dict:
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    return {"routes": golden["commands"], "fields": golden["command_fields"]}


class FakeDomia:
    def __init__(
        self,
        house: dict | None = None,
        observations: list | None = None,
        refuse: dict | None = None,
        weather: dict | None = None,
        habits: dict | None = None,
        journal: list | None = None,
        notifications: list | None = None,
    ):
        self._house = copy.deepcopy(house or HOUSE)
        self._observations = observations or []
        self._weather = weather or {"reason": "NO_SITE"}
        self._habits = habits or {"groups": {}}
        self._journal = journal
        self._notifications = notifications or []
        self.refuse = refuse or {}  # chemin → code d'erreur
        self.gestures: list[tuple[str, str, dict | None, str | None]] = []
        self.notices: list[tuple[str, str]] = []

    def house(self):
        return copy.deepcopy(self._house)

    def facts(self):
        return {"household": {}, "estimates": {}}

    def observations(self):
        return list(self._observations)

    def weather(self):
        return copy.deepcopy(self._weather)

    def habits(self, days=28):
        return copy.deepcopy(self._habits)

    def catalog(self):
        return catalog()

    def memory_summary(self):
        return {"days": []}

    def memory(self, start, end):
        return [
            {"v": 1, "at": "2026-10-24T21:40:00Z", "kind": "state", "situation": "NIGHT"},
            {"v": 1, "at": "2026-10-24T21:41:12Z", "kind": "situation", "from": "DAY", "to": "NIGHT", "origin": "UI"},
            {
                "v": 1,
                "at": "2026-10-25T05:58:00Z",
                "kind": "situation",
                "from": "NIGHT",
                "to": "DAY",
                "origin": "AUTOMATION",
            },
        ]

    def journal(self, start=None, end=None, types=None, entities=None):
        lines = (
            copy.deepcopy(self._journal)
            if self._journal is not None
            else [{"type": "command", "command": {"name": "LightAction", "args": {"light_id": "living_ceiling"}}}]
        )
        self.journal_asked = (types, entities)
        if types:
            lines = [line for line in lines if line.get("type") in types]
        if entities:
            lines = [
                line
                for line in lines
                if line.get("type") != "entity_change" or line["entity_change"]["entity_id"] in entities
            ]
        return lines

    def config(self):
        if not hasattr(self, "_config"):
            self._config = golden("config.golden.json")
        return copy.deepcopy(self._config)

    def config_preview(self, config, revision):
        """Domia vérifie : un délai négatif est refusé, comme ConfigValidator ; rien n'est écrit."""
        self.previews = getattr(self, "previews", 0) + 1
        if revision != self.config()["config_revision"]:
            raise DomiaError(409, "CONFIG_CONFLICT", "révision")
        bad = [{"path": k, "message": "doit être positif"} for k in _numbers(config) if _numbers(config)[k] < 0]
        return {"valid": not bad, "messages": bad, "warnings": [], "removed": {}}

    def config_put(self, config, revision, person):
        if revision != self.config()["config_revision"]:
            raise DomiaError(409, "CONFIG_CONFLICT", "révision")
        config = copy.deepcopy(config)
        for room in config.get("rooms", []):  # Domia donne les ids des objets neufs
            for plural in ("lights", "appliances", "covers", "sensors", "emitters"):
                for i, o in enumerate(room.get(plural) or []):
                    o.setdefault("id", f"{room['id']}_{plural}_{i}")
        self._config = {"config_revision": revision + 1, "config": config}
        self.gestures.append(("PUT", "/api/config", None, person))
        return {"config_revision": revision + 1}

    def health(self):
        return golden("health.golden.json")

    def notifications(self):
        return copy.deepcopy(self._notifications)

    def notify_services(self):
        return [{"id": "mobile_app_iphone", "name": "iPhone"}]

    def ha_entities(self):
        return golden("ha_entities.golden.json")

    def notify_test(self, service, person):
        self.gestures.append(("POST", "/api/notify/test", {"service": service}, person))
        return {"status": "APPLIED"}

    def gesture(self, method, path, body, person):
        if path in self.refuse:
            raise DomiaError(409, self.refuse[path], "refusé")
        self.gestures.append((method, path, body, person))
        if path == "/api/situation" and body:
            self._house["situation"]["value"] = body["value"]
        return {"status": "APPLIED"}

    def notify(self, title, message):
        self.notices.append((title, message))
        return {"status": "APPLIED"}


def _numbers(value, path=""):
    """Les nombres d'un document, par chemin : de quoi refuser un délai négatif."""
    out = {}
    if isinstance(value, dict):
        for k, v in value.items():
            out.update(_numbers(v, f"{path}.{k}" if path else k))
    elif isinstance(value, list):
        for i, v in enumerate(value):
            out.update(_numbers(v, f"{path}[{i}]"))
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        out[path] = value
    return out
