"""Client des routes d'outils du hub (`/api/tools`). Transport remplaçable pour les tests."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

Transport = Callable[[str, str, dict[str, str], bytes | None], tuple[int, bytes]]


def urllib_transport(
    method: str, url: str, headers: dict[str, str], data: bytes | None
) -> tuple[int, bytes]:  # pragma: no cover - réseau
    request = urllib.request.Request(url, data=data, method=method, headers=headers)  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


class HubError(RuntimeError):
    def __init__(self, status: int, type_: str, detail: str | None = None) -> None:
        self.status = status
        self.type = type_
        self.detail = detail
        super().__init__(f"{type_} ({status})" + (f" : {detail}" if detail else ""))


def loads(raw: bytes) -> Any:
    """JSON sans flottant : un nombre décimal reste du texte."""
    return json.loads(raw or b"null", parse_float=str)


class HubApi:
    def __init__(self, base_url: str, token: str, transport: Transport | None = None) -> None:
        self.base = base_url.rstrip("/") + "/api/tools"
        self.token = token
        self.transport = transport or urllib_transport

    def _call(self, method: str, path: str, body: Any = None) -> Any:
        headers = {"Authorization": f"Bearer {self.token}", "Accept": "application/json"}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        try:
            status, raw = self.transport(method, self.base + path, headers, data)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise HubError(0, "hub.unreachable", type(exc).__name__) from None
        if status >= 400:
            try:
                problem = loads(raw)
            except ValueError:
                problem = {}
            problem = problem if isinstance(problem, dict) else {}
            raise HubError(
                status, str(problem.get("type") or f"http_{status}"), problem.get("detail")
            )
        return loads(raw)

    def capabilities(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = self._call("GET", "")["domains"]
        return out

    def tools(self, domain: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = self._call("GET", "/" + urllib.parse.quote(domain))["items"]
        return out

    def call(self, domain: str, name: str, args: dict[str, Any]) -> Any:
        path = f"/{urllib.parse.quote(domain)}/{urllib.parse.quote(name)}"
        return self._call("POST", path, args)["result"]
