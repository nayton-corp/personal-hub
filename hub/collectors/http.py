"""Appels HTTP des collecteurs sans navigateur (IBKR, cours du marché) : un transport
remplaçable pour les tests, des échecs typés, et du JSON lu sans flottant."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

from hub.collectors.base import Failure

Transport = Callable[[str, str, dict[str, str], bytes | None], tuple[int, bytes]]
USER_AGENT = "personal-hub-collector/1.0"


def urllib_transport(
    method: str, url: str, headers: dict[str, str], data: bytes | None
) -> tuple[int, bytes]:
    request = urllib.request.Request(url, data=data, method=method, headers=headers)  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


class Http:
    def __init__(self, transport: Transport | None = None) -> None:
        self.transport = transport or urllib_transport

    def call(
        self,
        url: str,
        step: str,
        *,
        method: str = "GET",
        body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> bytes:
        h = {"User-Agent": USER_AGENT, "Accept": "*/*", **(headers or {})}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            h["Content-Type"] = "application/json"
        try:
            status, raw = self.transport(method, url, h, data)
        except (urllib.error.URLError, TimeoutError, OSError):
            raise Failure("site_unavailable", f"{step}:network") from None
        if status in (401, 403):
            raise Failure("auth_error", f"{step}:http_{status}")
        if status != 200:
            raise Failure("site_unavailable", f"{step}:http_{status}")
        return raw

    def json(self, url: str, step: str, **kw: Any) -> Any:
        raw = self.call(url, step, **kw)
        try:
            return json.loads(raw, parse_float=str)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise Failure("invalid_file", f"{step}:json") from None
