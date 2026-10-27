"""Client Enable Banking (API AIS en lecture seule), pour Revolut.

Authentification par JWT RS256 signé avec la clé privée de l'application (mode production
restreint : seuls les comptes que tu relies toi-même). Aucune dépendance en plus de
`cryptography`, déjà présente dans l'image des collecteurs.
"""

from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

from hub.collectors.base import Failure

Transport = Callable[[str, str, dict[str, str], bytes | None], tuple[int, bytes]]
MAX_PAGES = 200


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def jwt(application_id: str, private_key_pem: str, now: int | None = None) -> str:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding, rsa

    key = serialization.load_pem_private_key(private_key_pem.encode(), password=None)
    if not isinstance(key, rsa.RSAPrivateKey):
        raise Failure("auth_error", "eb.key_not_rsa")
    iat = int(now if now is not None else time.time())
    header = {"typ": "JWT", "alg": "RS256", "kid": application_id}
    body = {
        "iss": "enablebanking.com",
        "aud": "api.enablebanking.com",
        "iat": iat,
        "exp": iat + 3600,
    }
    signing_input = (
        _b64url(json.dumps(header, separators=(",", ":")).encode())
        + "."
        + _b64url(json.dumps(body, separators=(",", ":")).encode())
    )
    signature = key.sign(signing_input.encode(), padding.PKCS1v15(), hashes.SHA256())
    return signing_input + "." + _b64url(signature)


def _urllib(
    method: str, url: str, headers: dict[str, str], data: bytes | None
) -> tuple[int, bytes]:
    request = urllib.request.Request(url, data=data, method=method, headers=headers)  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


class EnableBanking:
    def __init__(
        self,
        base_url: str,
        application_id: str,
        private_key_pem: str,
        transport: Transport | None = None,
    ) -> None:
        self.base = base_url.rstrip("/")
        self.application_id = application_id
        self.private_key_pem = private_key_pem
        self.transport = transport or _urllib

    def _call(
        self, method: str, path: str, body: dict[str, Any] | None = None, step: str = "eb"
    ) -> Any:
        headers = {
            "Authorization": f"Bearer {jwt(self.application_id, self.private_key_pem)}",
            "Content-Type": "application/json",
        }
        data = json.dumps(body).encode() if body is not None else None
        try:
            status, raw = self.transport(method, self.base + path, headers, data)
        except (urllib.error.URLError, TimeoutError, OSError):
            raise Failure("site_unavailable", f"{step}:network") from None
        if status in (401, 403):
            raise Failure("auth_error", f"{step}:http{status}")
        if status == 429 or status >= 500:
            raise Failure("site_unavailable", f"{step}:http{status}")
        if status >= 400:
            # consentement expiré ou révoqué, session inconnue : il faut une nouvelle liaison
            raise Failure("auth_error", f"{step}:http{status}")
        try:
            return json.loads(raw or b"null")
        except json.JSONDecodeError:
            raise Failure("invalid_file", f"{step}:json") from None

    # --- liaison ------------------------------------------------------------------------------

    def aspsps(self, country: str) -> list[dict[str, Any]]:
        out = self._call("GET", "/aspsps?" + urllib.parse.urlencode({"country": country}))
        return list(out.get("aspsps", []))

    def start_auth(
        self,
        *,
        aspsp: str,
        country: str,
        valid_until: str,
        redirect_url: str,
        state: str,
        psu_type: str,
    ) -> str:
        out = self._call(
            "POST",
            "/auth",
            {
                "access": {"valid_until": valid_until},
                "aspsp": {"name": aspsp, "country": country},
                "state": state,
                "redirect_url": redirect_url,
                "psu_type": psu_type,
            },
            "eb.auth",
        )
        return str(out["url"])

    def create_session(self, code: str) -> dict[str, Any]:
        out: dict[str, Any] = self._call("POST", "/sessions", {"code": code}, "eb.session")
        return out

    def session(self, session_id: str) -> dict[str, Any]:
        out: dict[str, Any] = self._call("GET", f"/sessions/{session_id}", step="eb.session")
        return out

    # --- lecture ------------------------------------------------------------------------------

    def balances(self, uid: str) -> list[dict[str, Any]]:
        out = self._call("GET", f"/accounts/{uid}/balances", step="eb.balances")
        return list(out.get("balances", []))

    def transactions(self, uid: str, date_from: str, date_to: str) -> list[dict[str, Any]]:
        params = {"date_from": date_from, "date_to": date_to}
        items: list[dict[str, Any]] = []
        for _ in range(MAX_PAGES):
            out = self._call(
                "GET",
                f"/accounts/{uid}/transactions?" + urllib.parse.urlencode(params),
                step="eb.transactions",
            )
            items += list(out.get("transactions", []))
            key = out.get("continuation_key")
            if not key:
                return items
            params["continuation_key"] = key
        raise Failure("unknown", "eb.transactions:too_many_pages")
