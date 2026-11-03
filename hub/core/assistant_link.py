"""Le lien vers l'assistant de la maison (`assistant/`, natif sur le Mac).

L'app ne joint jamais l'assistant elle-même : elle passe par le hub, qui garde la session et
le seul chemin réseau (`host.docker.internal`). Le hub relaie la phrase, l'historique et le son,
sans rien garder. Il se présente à l'assistant avec son jeton (`secrets.enc.yaml`, section
`assistant`, clé `token`) : l'assistant en déduit pour qui le hub parle, le hub ne nomme jamais
la personne. Transport remplaçable pour les tests.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

from hub.platform import secrets
from hub.platform.settings import Settings

# (méthode, url, corps, en-têtes, délai en secondes) -> (statut, corps)
Transport = Callable[[str, str, bytes | None, dict[str, str], int], tuple[int, bytes]]
TALK_SECONDS = 120  # un modèle local peut réfléchir longtemps
READ_SECONDS = 10


class AssistantError(RuntimeError):
    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind  # unconfigured, unreachable, failed


def urllib_transport(
    method: str, url: str, data: bytes | None, headers: dict[str, str], timeout: int
) -> tuple[int, bytes]:  # pragma: no cover - réseau
    request = urllib.request.Request(  # noqa: S310 - adresse des réglages
        url, data=data, method=method, headers=headers
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def token(settings: Settings) -> str | None:
    """Le jeton que le hub présente à l'assistant ; None sans secrets ou sans la clé."""
    try:
        value = secrets.section(
            settings.secrets.file, settings.secrets.age_key_file, "assistant"
        ).get("token")
    except secrets.SecretsError:
        return None
    return value.strip() if isinstance(value, str) and value.strip() else None


class AssistantLink:
    def __init__(
        self, base_url: str | None, transport: Transport | None = None, token: str | None = None
    ) -> None:
        self.base = base_url.rstrip("/") if base_url else None
        self.transport = transport or urllib_transport
        self._token = token

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
        headers = {"Content-Type": mime}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        try:
            status, raw = self.transport(method, self.base + path, data, headers, timeout)
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

    def history(self, days: int, limit: int) -> dict[str, Any]:
        query = {"days": str(days), "limit": str(limit)}
        return self._call("GET", "/history?" + urllib.parse.urlencode(query))

    def talk(self, text: str) -> dict[str, Any]:
        body = {"text": text, "client": "hub"}
        return self._call("POST", "/talk", json.dumps(body).encode(), timeout=TALK_SECONDS)

    def voice(self, audio: bytes, mime: str) -> dict[str, Any]:
        path = "/voice?" + urllib.parse.urlencode({"client": "hub"})
        return self._call("POST", path, audio, mime, TALK_SECONDS)
