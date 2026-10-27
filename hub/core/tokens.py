"""Jetons à portée : 256 bits aléatoires, montrés une seule fois, stockés en empreinte."""

from __future__ import annotations

import hashlib
import re
import secrets
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Connection, Row, text

from hub.core.clock import now_iso
from hub.core.coredb import audit
from hub.core.ids import actor, new_id

TOKEN_PREFIX = "hub_"  # noqa: S105 - préfixe, pas un secret

# raccourcis à la création d'un jeton (revue d'architecture, section 3)
SHORTCUTS: dict[str, tuple[str, ...]] = {
    "brain": ("finance:read", "finance:propose"),
    "aggregates": ("*:aggregates",),
    "collector": ("core:collector",),
}
DOMAIN_SCOPE = re.compile(r"^(?P<domain>[a-z][a-z0-9_-]*|\*):(?P<verb>read|propose|aggregates)$")
CORE_SCOPES = frozenset({"core:collector"})


class ScopeError(ValueError):
    pass


def expand_scopes(requested: list[str]) -> list[str]:
    out: set[str] = set()
    for item in requested:
        for scope in SHORTCUTS.get(item, (item,)):
            if scope == "app":
                raise ScopeError("la portée app est réservée à la session passkey")
            m = DOMAIN_SCOPE.match(scope)
            if scope not in CORE_SCOPES and m is None:
                raise ScopeError(f"portée inconnue : {scope}")
            if m is not None and m["domain"] == "*" and m["verb"] != "aggregates":
                raise ScopeError("seule la portée aggregates accepte le joker *")
            out.add(scope)
    if not out:
        raise ScopeError("au moins une portée est requise")
    return sorted(out)


def hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


@dataclass(frozen=True)
class TokenInfo:
    id: str
    name: str
    scopes: tuple[str, ...]
    created_at: str
    last_used_at: str | None
    revoked_at: str | None

    @property
    def actor(self) -> str:
        return actor("token", self.id)


def create(conn: Connection, name: str, scopes: list[str], by: str) -> tuple[TokenInfo, str]:
    """Renvoie le jeton en clair : c'est la seule fois qu'il existe hors de son détenteur."""
    expanded = expand_scopes(scopes)
    token_id = new_id()
    secret = TOKEN_PREFIX + secrets.token_urlsafe(32)
    created = now_iso()
    conn.execute(
        text(
            "INSERT INTO tokens (id, name, scopes, secret_hash, created_at) "
            "VALUES (:id, :name, :scopes, :hash, :at)"
        ),
        {
            "id": token_id,
            "name": name,
            "scopes": " ".join(expanded),
            "hash": hash_secret(secret),
            "at": created,
        },
    )
    audit(conn, by, "token.create", f"token:{token_id}", "ok")
    return TokenInfo(token_id, name, tuple(expanded), created, None, None), secret


def _row(r: Row[Any]) -> TokenInfo:
    m = r._mapping
    return TokenInfo(
        m["id"],
        m["name"],
        tuple(m["scopes"].split()),
        m["created_at"],
        m["last_used_at"],
        m["revoked_at"],
    )


def list_all(conn: Connection) -> list[TokenInfo]:
    rows = conn.execute(text("SELECT * FROM tokens ORDER BY created_at, id")).fetchall()
    return [_row(r) for r in rows]


def revoke(conn: Connection, token_id: str, by: str) -> bool:
    res = conn.execute(
        text("UPDATE tokens SET revoked_at = :at WHERE id = :id AND revoked_at IS NULL"),
        {"at": now_iso(), "id": token_id},
    )
    done = res.rowcount == 1
    audit(conn, by, "token.revoke", f"token:{token_id}", "ok" if done else "noop")
    return done


def verify(conn: Connection, secret: str) -> TokenInfo | None:
    if not secret.startswith(TOKEN_PREFIX):
        return None
    row = conn.execute(
        text("SELECT * FROM tokens WHERE secret_hash = :h AND revoked_at IS NULL"),
        {"h": hash_secret(secret)},
    ).fetchone()
    if row is None:
        return None
    conn.execute(
        text("UPDATE tokens SET last_used_at = :at WHERE id = :id"),
        {"at": now_iso(), "id": row._mapping["id"]},
    )
    return _row(row)
