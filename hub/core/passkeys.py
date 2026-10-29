"""WebAuthn : inscription (code d'amorçage ou session existante) et connexion par passkey.

Les défis vivent dans `core.db` (`webauthn_challenges`), jamais en mémoire, et ne servent
qu'une fois.
"""

from __future__ import annotations

import json
import secrets
from datetime import timedelta
from typing import Any

from sqlalchemy import Connection, text
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
from webauthn.helpers.exceptions import InvalidAuthenticationResponse, InvalidRegistrationResponse
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from hub.core.coredb import audit
from hub.core.errors import Problem
from hub.kernel.clock import iso, now_iso, utcnow
from hub.kernel.ids import actor, new_id
from hub.platform.settings import Settings

# un seul utilisateur : identifiant fixe, jamais une donnée personnelle
USER_HANDLE = b"personal-hub-owner"
USER_NAME = "owner"


def _store_challenge(
    conn: Connection, purpose: str, challenge: bytes, seconds: int, bound: str | None = None
) -> str:
    challenge_id = new_id()
    conn.execute(
        text(
            "INSERT INTO webauthn_challenges (id, purpose, challenge, bound_digest, expires_at) "
            "VALUES (:id, :p, :c, :b, :e)"
        ),
        {
            "id": challenge_id,
            "p": purpose,
            "c": challenge,
            "b": bound,
            "e": iso(utcnow() + timedelta(seconds=seconds)),
        },
    )
    return challenge_id


def _take_challenge(conn: Connection, challenge_id: str, purpose: str) -> tuple[bytes, str | None]:
    row = conn.execute(
        text(
            "DELETE FROM webauthn_challenges WHERE id = :id AND purpose = :p "
            "RETURNING challenge, bound_digest, expires_at"
        ),
        {"id": challenge_id, "p": purpose},
    ).fetchone()
    if row is None or row.expires_at <= now_iso():
        raise Problem("auth.challenge_expired")
    return bytes(row.challenge), row.bound_digest


def purge_challenges(conn: Connection) -> int:
    return conn.execute(
        text("DELETE FROM webauthn_challenges WHERE expires_at <= :now"), {"now": now_iso()}
    ).rowcount


def _credentials(conn: Connection) -> list[PublicKeyCredentialDescriptor]:
    rows = conn.execute(text("SELECT credential_id FROM passkeys")).fetchall()
    return [PublicKeyCredentialDescriptor(id=base64url_to_bytes(r[0])) for r in rows]


def count(conn: Connection) -> int:
    value: int = conn.execute(text("SELECT count(*) FROM passkeys")).scalar_one()
    return value


def registration_options(conn: Connection, settings: Settings) -> dict[str, Any]:
    options = generate_registration_options(
        rp_id=settings.server.rp_id,
        rp_name=settings.auth.rp_name,
        user_id=USER_HANDLE,
        user_name=USER_NAME,
        user_display_name=settings.auth.rp_name,
        challenge=secrets.token_bytes(32),
        exclude_credentials=_credentials(conn),
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.REQUIRED,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
    )
    challenge_id = _store_challenge(
        conn, "register", options.challenge, settings.auth.challenge_seconds
    )
    return {"challenge_id": challenge_id, "options": json.loads(options_to_json(options))}


def register(
    conn: Connection,
    settings: Settings,
    challenge_id: str,
    credential: dict[str, Any],
    device_name: str | None,
    by: str,
) -> str:
    challenge, _ = _take_challenge(conn, challenge_id, "register")
    try:
        verified = verify_registration_response(
            credential=credential,
            expected_challenge=challenge,
            expected_rp_id=settings.server.rp_id,
            expected_origin=settings.server.public_origin,
            require_user_verification=True,
        )
    except InvalidRegistrationResponse as exc:
        raise Problem("auth.passkey_invalid", "inscription refusée") from exc
    credential_id = bytes_to_base64url(verified.credential_id)
    transports = credential.get("response", {}).get("transports") or []
    conn.execute(
        text(
            "INSERT INTO passkeys (credential_id, public_key, sign_count, device_name, transports, "
            "created_at) VALUES (:id, :pk, :n, :name, :tr, :at)"
        ),
        {
            "id": credential_id,
            "pk": verified.credential_public_key,
            "n": verified.sign_count,
            "name": (device_name or "")[:60] or None,
            "tr": " ".join(map(str, transports)) or None,
            "at": now_iso(),
        },
    )
    audit(conn, by, "passkey.register", actor("passkey", credential_id), "ok")
    return credential_id


def login_options(conn: Connection, settings: Settings) -> dict[str, Any]:
    options = generate_authentication_options(
        rp_id=settings.server.rp_id,
        challenge=secrets.token_bytes(32),
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    challenge_id = _store_challenge(
        conn, "login", options.challenge, settings.auth.challenge_seconds
    )
    return {"challenge_id": challenge_id, "options": json.loads(options_to_json(options))}


def authenticate(
    conn: Connection, settings: Settings, challenge_id: str, credential: dict[str, Any]
) -> str:
    challenge, _ = _take_challenge(conn, challenge_id, "login")
    return authenticate_with(conn, settings, challenge, credential)


def authenticate_with(
    conn: Connection, settings: Settings, challenge: bytes, credential: dict[str, Any]
) -> str:
    credential_id = credential.get("id")
    if not isinstance(credential_id, str):
        raise Problem("auth.passkey_invalid")
    row = conn.execute(
        text("SELECT public_key, sign_count FROM passkeys WHERE credential_id = :id"),
        {"id": credential_id},
    ).fetchone()
    if row is None:
        raise Problem("auth.passkey_invalid", "passkey inconnue")
    try:
        verified = verify_authentication_response(
            credential=credential,
            expected_challenge=challenge,
            expected_rp_id=settings.server.rp_id,
            expected_origin=settings.server.public_origin,
            credential_public_key=bytes(row.public_key),
            credential_current_sign_count=row.sign_count,
            require_user_verification=True,
        )
    except InvalidAuthenticationResponse as exc:
        raise Problem("auth.passkey_invalid") from exc
    conn.execute(
        text("UPDATE passkeys SET sign_count = :n, last_used_at = :at WHERE credential_id = :id"),
        {"n": verified.new_sign_count, "at": now_iso(), "id": credential_id},
    )
    return credential_id


def approval_options(conn: Connection, settings: Settings, digest: str) -> dict[str, Any]:
    """Défi de validation : il commence par `approval_digest`, ce que la passkey signe porte
    donc sur ces propositions, à ces révisions et ces empreintes."""
    challenge = bytes.fromhex(digest) + secrets.token_bytes(16)
    options = generate_authentication_options(
        rp_id=settings.server.rp_id,
        challenge=challenge,
        user_verification=UserVerificationRequirement.REQUIRED,
        allow_credentials=_credentials(conn),
    )
    challenge_id = _store_challenge(
        conn, "approve", options.challenge, settings.auth.challenge_seconds, bound=digest
    )
    return {"challenge_id": challenge_id, "options": json.loads(options_to_json(options))}


def verify_approval(
    conn: Connection,
    settings: Settings,
    challenge_id: str,
    credential: dict[str, Any],
    digest: str,
) -> dict[str, Any]:
    """Vérifie une validation signée ; renvoie ce qui est gardé dans `signature_json`."""
    try:
        challenge, bound = _take_challenge(conn, challenge_id, "approve")
    except Problem:
        raise Problem("approval.signature_invalid", "défi expiré ou inconnu") from None
    if bound != digest:
        raise Problem("approval.signature_invalid", "la signature porte sur un autre aperçu")
    try:
        credential_id = authenticate_with(conn, settings, challenge, credential)
    except Problem:
        raise Problem("approval.signature_invalid") from None
    return {
        "credential_id": credential_id,
        "challenge_id": challenge_id,
        "approval_digest": digest,
        "assertion": credential,
    }


def list_all(conn: Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            "SELECT credential_id, device_name, created_at, last_used_at FROM passkeys "
            "ORDER BY created_at"
        )
    ).fetchall()
    return [
        {
            "id": r.credential_id,
            "device_name": r.device_name,
            "created_at": r.created_at,
            "last_used_at": r.last_used_at,
        }
        for r in rows
    ]
