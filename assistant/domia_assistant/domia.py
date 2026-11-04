"""Le client de l'API de Domia : lectures ouvertes, gestes avec le jeton de l'appareil autorisé ASSISTANT et la
personne pour qui l'assistant parle (spec §4.2, en-tête X-Domia-On-Behalf-Of). La config se lit, se vérifie et
s'écrit (spec de l'assistant complet §5) : derrière Nginx, son écriture demande en plus le mot de passe de la
configuration (htpasswd), envoyé en Basic avec le jeton en cookie, comme un écran jumelé."""

from __future__ import annotations

import base64
import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from .memory import Memory

LOG = logging.getLogger("assistant.notify")

ON_BEHALF_OF = "X-Domia-On-Behalf-Of"


@dataclass
class DomiaError(Exception):
    status: int
    code: str
    message: str

    def __str__(self) -> str:
        return f"{self.code} : {self.message}"


class Domia:
    def __init__(self, base_url: str, token: str, timeout: float = 10.0, config_auth: tuple[str, str] | None = None):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self.config_auth = config_auth  # (utilisateur, mot de passe) du htpasswd ; None : Domia sans Nginx (essai, Dev)

    def _call(
        self,
        method: str,
        path: str,
        body: Any = None,
        person: str | None = None,
        raw: bool = False,
        headers: dict[str, str] | None = None,
    ) -> Any:
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(self.base_url + path, data=data, method=method)
        if path.startswith("/api/config") and method != "GET" and self.config_auth:
            user, password = self.config_auth
            request.add_header("Authorization", "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode())
            request.add_header("Cookie", f"domia_session={self.token}")
        else:
            request.add_header("Authorization", f"Bearer {self.token}")
        for name, value in (headers or {}).items():
            request.add_header(name, value)
        if data is not None:
            request.add_header("Content-Type", "application/json")
        if person:
            request.add_header(ON_BEHALF_OF, person)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                text = response.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            text = e.read().decode("utf-8", "replace")
            try:
                error = json.loads(text)["error"]
                raise DomiaError(e.code, error.get("code", "HTTP"), error.get("message", "")) from None
            except (ValueError, KeyError, TypeError):
                raise DomiaError(e.code, f"HTTP_{e.code}", text[:200]) from None
        except (urllib.error.URLError, TimeoutError) as e:
            raise DomiaError(0, "NETWORK", str(e)) from None
        if raw:
            return text
        return json.loads(text) if text.strip() else None

    # lectures (spec §7.1)
    def house(self) -> dict[str, Any]:
        return cast("dict[str, Any]", self._call("GET", "/api/house"))

    def facts(self) -> dict[str, Any]:
        return cast("dict[str, Any]", self._call("GET", "/api/facts"))

    def observations(self) -> list[dict[str, Any]]:
        return cast("list[dict[str, Any]]", self._call("GET", "/api/observations")["observations"])

    def catalog(self) -> dict[str, Any]:
        return cast("dict[str, Any]", self._call("GET", "/api/commands/catalog"))

    def memory_summary(self) -> dict[str, Any]:
        return cast("dict[str, Any]", self._call("GET", "/api/memory/summary"))

    def memory(self, start: str, end: str) -> list[dict[str, Any]]:
        """Les lignes de la mémoire longue de ces jours (AAAA-MM-JJ, au plus 92)."""
        text = self._call("GET", "/api/memory?" + urllib.parse.urlencode({"from": start, "to": end}), raw=True)
        return [json.loads(line) for line in text.splitlines() if line.strip()]

    def weather(self) -> dict[str, Any]:
        """La prévision de la maison ; `reason` dit pourquoi il n'y en a pas, `stale` si elle est vieille."""
        return cast("dict[str, Any]", self._call("GET", "/api/weather"))

    def habits(self, days: int = 28) -> dict[str, Any]:
        """Le coucher, le lever, les départs et retours habituels, par jour de semaine."""
        return cast("dict[str, Any]", self._call("GET", f"/api/memory/habits?days={days}"))

    def journal(
        self,
        start: str | None = None,
        end: str | None = None,
        types: list[str] | None = None,
        entities: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Le journal ; avec `types` et `entities`, un extrait (sans les tics ni les points de reprise : 59 Mo par jour
        sur la vraie maison, 14 s de transfert depuis le Pi)."""
        pairs = [(k, v) for k, v in (("from", start), ("to", end)) if v]
        pairs += [("type", t) for t in types or []] + [("entity", e) for e in sorted(entities or [])]
        query = urllib.parse.urlencode(pairs)
        text = self._call("GET", "/api/journal" + (f"?{query}" if query else ""), raw=True)
        return [json.loads(line) for line in text.splitlines() if line.strip()]

    def config(self) -> dict[str, Any]:
        """Le document de config normalisé et sa révision."""
        return cast("dict[str, Any]", self._call("GET", "/api/config"))

    def config_preview(self, config: dict[str, Any], revision: int) -> dict[str, Any]:
        """Domia vérifie une config sans l'appliquer : valid, messages, warnings, removed."""
        return cast(
            "dict[str, Any]", self._call("POST", "/api/config/preview", config, headers={"If-Match": f'"{revision}"'})
        )

    def config_put(self, config: dict[str, Any], revision: int, person: str | None) -> dict[str, Any]:
        return cast(
            "dict[str, Any]",
            self._call("PUT", "/api/config", config, person=person, headers={"If-Match": f'"{revision}"'}),
        )

    def health(self) -> dict[str, Any]:
        return cast("dict[str, Any]", self._call("GET", "/api/health"))

    def notifications(self) -> list[dict[str, Any]]:
        return cast("list[dict[str, Any]]", self._call("GET", "/api/notifications"))

    def notify_services(self) -> list[dict[str, Any]]:
        return cast("list[dict[str, Any]]", self._call("GET", "/api/notify/services"))

    def ha_entities(self) -> list[dict[str, Any]]:
        return cast("list[dict[str, Any]]", self._call("GET", "/api/ha/entities"))

    def notify_test(self, service: str, person: str | None) -> dict[str, Any] | None:
        return cast(
            "dict[str, Any] | None", self._call("POST", "/api/notify/test", {"service": service}, person=person)
        )

    # gestes (spec §7.2) : la route et le corps viennent du catalogue
    def gesture(self, method: str, path: str, body: dict[str, Any] | None, person: str | None) -> dict[str, Any] | None:
        return cast("dict[str, Any] | None", self._call(method, path, body, person=person))

    def notify(self, title: str, message: str) -> dict[str, Any] | None:
        return cast(
            "dict[str, Any] | None", self._call("POST", "/api/notify/assistant", {"title": title, "message": message})
        )


class Noting:
    """Domia, avec chaque notification de l'assistant gardée dans la mémoire (spec de l'écran §7) : l'écran Assistant
    montre le plan du soir, les remarques et les engagements tenus dans la conversation. Le seul endroit où elles
    partent ; le reste passe tel quel."""

    def __init__(self, domia: Domia, memory: Memory):
        self._domia = domia
        self._memory = memory

    def __getattr__(self, name: str) -> Any:
        return getattr(self._domia, name)

    def notify(self, title: str, message: str) -> dict[str, Any] | None:
        result = self._domia.notify(title, message)
        self._memory.message(title, message)
        LOG.info(
            "notify sent title=%s chars=%d", title, len(message)
        )  # le brief de 21 h et les remarques, suivis au log
        return result
