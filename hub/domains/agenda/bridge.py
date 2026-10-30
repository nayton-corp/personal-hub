"""Client du pont Rappels/Calendrier (`assistant/eventkit/`, le seul morceau attaché à Apple).

Le pont tourne sur le Mac, à l'écoute du Mac seul ; le hub, en conteneur, le joint par
`host.docker.internal`. Il lit, ajoute et coche ; il ne supprime jamais. Transport remplaçable
pour les tests.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

Transport = Callable[[str, str, bytes | None], tuple[int, bytes]]
SHOPPING = "Courses"


class BridgeError(RuntimeError):
    """`unreachable` : l'appel a pu partir ou non (l'effet est inconnu) ; sinon un refus net."""

    def __init__(self, message: str, *, unreachable: bool = False) -> None:
        super().__init__(message)
        self.unreachable = unreachable


def urllib_transport(
    method: str, url: str, data: bytes | None
) -> tuple[int, bytes]:  # pragma: no cover - réseau
    headers = {"Content-Type": "application/json"}
    request = urllib.request.Request(url, data=data, method=method, headers=headers)  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


class Bridge:
    def __init__(self, base_url: str | None, transport: Transport | None = None) -> None:
        self.base = base_url.rstrip("/") if base_url else None
        self.transport = transport or urllib_transport

    def _call(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        if not self.base:
            raise BridgeError("pas de pont Rappels/Calendrier configuré")
        data = None if body is None else json.dumps(body).encode()
        try:
            status, raw = self.transport(method, self.base + path, data)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise BridgeError(
                f"le pont ne répond pas ({type(exc).__name__})", unreachable=True
            ) from None
        payload = json.loads(raw or b"null")
        if status >= 400:
            error = payload.get("error") if isinstance(payload, dict) else None
            raise BridgeError(str(error or f"HTTP {status}"))
        return payload

    def status(self) -> dict[str, bool]:
        found = self._call("GET", "/health")
        return {"reminders": bool(found.get("reminders")), "calendar": bool(found.get("calendar"))}

    def reminders(self, list_name: str | None = None, done: bool = False) -> list[dict[str, Any]]:
        query = urllib.parse.urlencode(
            {k: v for k, v in (("list", list_name), ("done", "1" if done else None)) if v}
        )
        found: list[dict[str, Any]] = self._call(
            "GET", "/reminders" + (f"?{query}" if query else "")
        )
        return found

    def add_reminder(self, body: dict[str, Any]) -> dict[str, Any]:
        found: dict[str, Any] = self._call("POST", "/reminders", _clean(body))
        return found

    def complete(self, reminder_id: str) -> dict[str, Any]:
        quoted = urllib.parse.quote(reminder_id, safe="")
        found: dict[str, Any] = self._call("POST", f"/reminders/{quoted}/complete")
        return found

    def events(self, start: str, end: str) -> list[dict[str, Any]]:
        query = urllib.parse.urlencode({"from": start, "to": end})
        found: list[dict[str, Any]] = self._call("GET", f"/events?{query}")
        return found

    def add_event(self, body: dict[str, Any]) -> dict[str, Any]:
        found: dict[str, Any] = self._call("POST", "/events", _clean(body))
        return found


def _clean(body: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in body.items() if v is not None}
