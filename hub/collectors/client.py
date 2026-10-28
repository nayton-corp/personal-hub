"""Client minimal de l'API du hub, côté collecteur : état, déclaration des runs, notifications,
liaison d'un consentement. Jeton à portée `core:collector`, réseau compose « hub » seulement."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

from hub.collectors.base import Kind, Result

# pauses avant de réessayer une erreur 5xx ou réseau : « database is locked » côté hub dure
# quelques secondes et ne doit pas faire tomber un passage (ni une liaison en attente)
RETRY_PAUSES = (1, 3)


class HubUnavailable(RuntimeError):
    pass


class HubRefused(HubUnavailable):
    """Erreur 4xx : la réessayer ne changerait rien."""


class HubClient:
    def __init__(self, base_url: str, token: str, timeout: int = 10) -> None:
        self.base = base_url.rstrip("/") + "/api/collectors"
        self.token = token
        self.timeout = timeout
        self.pause: Callable[[int], None] = time.sleep

    def _call(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        for pause in (*RETRY_PAUSES, None):
            try:
                return self._once(method, path, body)
            except HubRefused:
                raise
            except HubUnavailable:
                if pause is None:
                    raise
                self.pause(pause)
        return None  # pragma: no cover - la boucle rend ou lève

    def _once(self, method: str, path: str, body: dict[str, Any] | None) -> Any:
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(  # noqa: S310 - URL des réglages
            self.base + path,
            data=data,
            method=method,
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:  # noqa: S310
                return json.loads(response.read() or b"null")
        except urllib.error.HTTPError as exc:
            if exc.code < 500:
                raise HubRefused(f"hub : HTTP {exc.code} sur {path}") from None
            raise HubUnavailable(f"hub : HTTP {exc.code} sur {path}") from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise HubUnavailable(f"hub injoignable ({type(exc).__name__})") from None

    def state(self, name: str) -> dict[str, Any]:
        out: dict[str, Any] = self._call("GET", f"/{name}")
        return out

    def report(self, name: str, kind: Kind, result: Result, started: str, ended: str) -> Any:
        return self._call(
            "POST",
            f"/{name}/runs",
            {
                "kind": kind,
                "outcome": result.outcome,
                "started_at": started,
                "ended_at": ended,
                "files": result.files,
                "detail": result.detail,
            },
        )

    def notify(self, name: str, event: str) -> bool:
        try:
            return bool(self._call("POST", f"/{name}/notify", {"event": event})["sent"])
        except HubUnavailable:
            return False

    def register_link(self, name: str, state: str) -> str:
        return str(self._call("POST", f"/{name}/links", {"state": state})["expires_at"])

    def take_link(self, name: str, state: str) -> str | None:
        code = self._call("GET", f"/{name}/links/{state}")["code"]
        return str(code) if code else None
