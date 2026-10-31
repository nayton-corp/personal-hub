"""Le lien vers l'assistant de la maison (`assistant/`, natif sur le Mac).

L'app ne joint jamais l'assistant elle-même : elle passe par le hub, qui garde la session et
le seul chemin réseau (`host.docker.internal`). Le hub relaie la phrase, l'historique et le son,
sans rien garder. Transport remplaçable pour les tests.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

# (méthode, url, corps, type du corps, délai en secondes) -> (statut, corps)
Transport = Callable[[str, str, bytes | None, str, int], tuple[int, bytes]]
TALK_SECONDS = 120  # un modèle local peut réfléchir longtemps
READ_SECONDS = 10


class AssistantError(RuntimeError):
    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind  # unconfigured, unreachable, failed


def urllib_transport(
    method: str, url: str, data: bytes | None, mime: str, timeout: int
) -> tuple[int, bytes]:  # pragma: no cover - réseau
    request = urllib.request.Request(  # noqa: S310 - adresse des réglages
        url, data=data, method=method, headers={"Content-Type": mime}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


class AssistantLink:
    def __init__(self, base_url: str | None, transport: Transport | None = None) -> None:
        self.base = base_url.rstrip("/") if base_url else None
        self.transport = transport or urllib_transport

    @property
    def configured(self) -> bool:
        return self.base is not None

    def _call(
        self,
        method: str,
        path: str,
        data: bytes | None = None,
        mime: str = "application/json",
        timeout: int = READ_SECONDS,
    ) -> dict[str, Any]:
        if not self.base:
            raise AssistantError("unconfigured", "aucun assistant configuré")
        try:
            status, raw = self.transport(method, self.base + path, data, mime, timeout)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise AssistantError("unreachable", type(exc).__name__) from None
        try:
            payload = json.loads(raw or b"null")
        except ValueError:
            payload = None
        if status >= 400 or not isinstance(payload, dict):
            error = payload.get("error") if isinstance(payload, dict) else None
            raise AssistantError("failed", str(error or f"HTTP {status}"))
        return payload

    def health(self) -> dict[str, Any]:
        return self._call("GET", "/health")

    def history(self, person: str | None, days: int, limit: int) -> dict[str, Any]:
        query = {"days": str(days), "limit": str(limit)}
        if person:
            query["person"] = person
        return self._call("GET", "/history?" + urllib.parse.urlencode(query))

    def talk(self, text: str, person: str | None) -> dict[str, Any]:
        body = {"text": text, "person": person, "client": "hub"}
        return self._call("POST", "/talk", json.dumps(body).encode(), timeout=TALK_SECONDS)

    def voice(self, audio: bytes, mime: str, person: str | None) -> dict[str, Any]:
        query = {"client": "hub", **({"person": person} if person else {})}
        path = "/voice?" + urllib.parse.urlencode(query)
        return self._call("POST", path, audio, mime, TALK_SECONDS)
