"""Sessions de l'app après passkey, et codes d'amorçage à usage unique."""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import Connection, text

from hub.core.clock import iso, now_iso, utcnow
from hub.core.coredb import audit
from hub.core.ids import actor, new_id


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


@dataclass(frozen=True)
class Session:
    id: str
    credential_id: str
    created_at: str
    expires_at: str

    @property
    def actor(self) -> str:
        return actor("passkey", self.credential_id)


def create(conn: Connection, credential_id: str, hours: int) -> tuple[Session, str]:
    """Renvoie la session et la valeur du cookie (seule copie : la base n'a que l'empreinte)."""
    cookie = secrets.token_urlsafe(32)
    now = utcnow()
    session = Session(_hash(cookie), credential_id, iso(now), iso(now + timedelta(hours=hours)))
    conn.execute(
        text(
            "INSERT INTO sessions (id, credential_id, created_at, expires_at) "
            "VALUES (:id, :cred, :created, :expires)"
        ),
        {
            "id": session.id,
            "cred": credential_id,
            "created": session.created_at,
            "expires": session.expires_at,
        },
    )
    audit(conn, session.actor, "session.create", None, "ok")
    return session, cookie


def get_valid(conn: Connection, cookie: str) -> Session | None:
    row = conn.execute(
        text(
            "SELECT id, credential_id, created_at, expires_at FROM sessions "
            "WHERE id = :id AND revoked_at IS NULL AND expires_at > :now"
        ),
        {"id": _hash(cookie), "now": now_iso()},
    ).fetchone()
    return Session(*row) if row is not None else None


def revoke(conn: Connection, cookie: str) -> None:
    conn.execute(
        text("UPDATE sessions SET revoked_at = :at WHERE id = :id AND revoked_at IS NULL"),
        {"at": now_iso(), "id": _hash(cookie)},
    )


def purge_expired(conn: Connection) -> int:
    res = conn.execute(text("DELETE FROM sessions WHERE expires_at <= :now"), {"now": now_iso()})
    return res.rowcount


def create_bootstrap_code(conn: Connection, minutes: int, by: str) -> str:
    """Code à saisir dans l'app pour inscrire une passkey ; donné par la CLI, sur la machine."""
    code = "-".join(secrets.token_hex(3) for _ in range(3))
    now = utcnow()
    conn.execute(
        text(
            "INSERT INTO bootstrap_codes (id, code_hash, created_at, expires_at) "
            "VALUES (:id, :h, :created, :expires)"
        ),
        {
            "id": new_id(),
            "h": _hash(code),
            "created": iso(now),
            "expires": iso(now + timedelta(minutes=minutes)),
        },
    )
    audit(conn, by, "bootstrap.create", None, "ok")
    return code


def consume_bootstrap_code(conn: Connection, code: str) -> bool:
    """Compare-and-set : un code ne sert qu'une fois, même avec deux appels simultanés."""
    res = conn.execute(
        text(
            "UPDATE bootstrap_codes SET used_at = :now "
            "WHERE code_hash = :h AND used_at IS NULL AND expires_at > :now"
        ),
        {"h": _hash(code.strip().lower()), "now": now_iso()},
    )
    return res.rowcount == 1


def check_bootstrap_code(conn: Connection, code: str) -> bool:
    row = conn.execute(
        text(
            "SELECT 1 FROM bootstrap_codes "
            "WHERE code_hash = :h AND used_at IS NULL AND expires_at > :now"
        ),
        {"h": _hash(code.strip().lower()), "now": now_iso()},
    ).fetchone()
    return row is not None
