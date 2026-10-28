"""Collecteur Coinbase : tous les portefeuilles du compte (ETH en staking compris), par l'API
Coinbase App v2 avec une clé CDP (JWT signé ES256, ou EdDSA pour une clé Ed25519). Clé avec la
permission « View » seulement."""

from __future__ import annotations

import base64
import json
import secrets as pysecrets
import time
from typing import Any
from urllib.parse import urlsplit

from hub.collectors.base import Failure
from hub.collectors.exchanges.common import runner
from hub.collectors.http import Http
from hub.collectors.runtime import Env

MAX_PAGES = 20


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def jwt(key_name: str, private_key: str, uri: str, now: int | None = None) -> str:
    """Jeton de 2 minutes pour une requête (`uri` : « GET api.coinbase.com/v2/accounts »)."""
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec, ed25519
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

    now = int(time.time()) if now is None else now
    pem = private_key.replace("\\n", "\n").strip()
    try:
        if pem.startswith("-----BEGIN"):
            key: Any = serialization.load_pem_private_key(pem.encode(), password=None)
            if not isinstance(key, ec.EllipticCurvePrivateKey):
                raise ValueError
            alg = "ES256"
        else:  # clé Ed25519 en base64 : graine de 32 octets (suivie de la clé publique)
            key = ed25519.Ed25519PrivateKey.from_private_bytes(base64.b64decode(pem)[:32])
            alg = "EdDSA"
    except ValueError:
        raise Failure("auth_error", "secret:private_key") from None
    header = {"alg": alg, "kid": key_name, "nonce": pysecrets.token_hex(16), "typ": "JWT"}
    payload = {"sub": key_name, "iss": "cdp", "nbf": now, "exp": now + 120, "uri": uri}
    signing_input = ".".join(
        _b64url(json.dumps(x, separators=(",", ":")).encode()) for x in (header, payload)
    ).encode()
    if alg == "ES256":
        r, s = decode_dss_signature(key.sign(signing_input, ec.ECDSA(hashes.SHA256())))
        signature = r.to_bytes(32, "big") + s.to_bytes(32, "big")
    else:
        signature = key.sign(signing_input)
    return signing_input.decode() + "." + _b64url(signature)


def fetch(env: Env, http: Http) -> list[tuple[str, Any]]:
    base = env.cfg.exchanges.coinbase_url
    host = urlsplit(base).netloc
    key_name, private_key = env.secret("key_name"), env.secret("private_key")
    out: list[tuple[str, Any]] = []
    path: str | None = "/v2/accounts?limit=100"
    for _page in range(MAX_PAGES):
        if not path:
            break
        token = jwt(key_name, private_key, f"GET {host}{path.split('?', 1)[0]}")
        doc = http.json(
            f"{base}{path}", "coinbase.accounts", headers={"Authorization": f"Bearer {token}"}
        )
        try:
            out += [(a["balance"]["currency"], a["balance"]["amount"]) for a in doc["data"]]
            path = (doc.get("pagination") or {}).get("next_uri") or None
        except (KeyError, TypeError, AttributeError):
            raise Failure("invalid_file", "coinbase.accounts") from None
    return out


run = runner(fetch)
