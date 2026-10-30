"""Jetons à portée : 256 bits aléatoires, montrés une seule fois, stockés en empreinte.

Chaque jeton a une date de fin (chantier S8) : il ne s'utilise plus après, se renouvelle par
`rotate` (nouveau secret, mêmes portées, l'ancien révoqué) et la tâche de nuit prévient 14 jours
avant. Le raccourci `brain` n'ouvre que les agrégats ; `brain=finance,agenda` ajoute la lecture
et les propositions des domaines nommés. `<domaine>:household` ouvre ce que tout le foyer peut
lire (les documents marqués « foyer », S12), ce que `…:read` ouvre aussi.
"""

from __future__ import annotations

import hashlib
import re
import secrets
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import Connection, Row, text

from hub.core.coredb import audit
from hub.kernel.clock import iso, now_iso, parse_iso, utcnow
from hub.kernel.ids import actor, new_id

TOKEN_PREFIX = "hub_"  # noqa: S105 - préfixe, pas un secret

# raccourcis à la création d'un jeton (revue d'architecture, section 3 ; S8 pour brain=…)
SHORTCUTS: dict[str, tuple[str, ...]] = {
    "brain": ("*:aggregates",),
    "aggregates": ("*:aggregates",),
    "collector": ("core:collector",),
}
DOMAIN_SCOPE = re.compile(
    r"^(?P<domain>[a-z][a-z0-9_-]*|\*):(?P<verb>read|propose|aggregates|household)$"
)
DOMAIN_NAME = re.compile(r"^[a-z][a-z0-9_-]*$")
CORE_SCOPES = frozenset({"core:collector"})
DEFAULT_DAYS = 90
MAX_DAYS = 366
WARN_DAYS = 14


class ScopeError(ValueError):
    pass


def expand_scopes(requested: list[str]) -> list[str]:
    out: set[str] = set()
    for item in requested:
        for scope in _shortcut(item):
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


def _shortcut(item: str) -> tuple[str, ...]:
    """`brain=finance,agenda` : les agrégats partout, la lecture et les propositions des
    domaines nommés ; un autre raccourci ou une portée telle quelle sinon."""
    name, eq, domains = item.partition("=")
    if not eq:
        return SHORTCUTS.get(item, (item,))
    names = [d.strip() for d in domains.split(",") if d.strip()]
    if name != "brain" or not names or not all(DOMAIN_NAME.match(d) for d in names):
        raise ScopeError(f"raccourci inconnu : {item} (ex. brain=finance)")
    return ("*:aggregates", *(f"{d}:{v}" for d in names for v in ("read", "propose")))


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
    expires_at: str

    @property
    def actor(self) -> str:
        return actor("token", self.id)

    @property
    def expired(self) -> bool:
        return self.expires_at <= now_iso()

    @property
    def state(self) -> str:
        return "révoqué" if self.revoked_at else "expiré" if self.expired else "actif"


def create(
    conn: Connection, name: str, scopes: list[str], by: str, *, days: int
) -> tuple[TokenInfo, str]:
    """Renvoie le jeton en clair : c'est la seule fois qu'il existe hors de son détenteur.
    `days` : durée de vie, de 1 à 366 jours ; aucun jeton sans date de fin."""
    if not 1 <= days <= MAX_DAYS:
        raise ScopeError(f"durée : de 1 à {MAX_DAYS} jours")
    expanded = expand_scopes(scopes)
    token_id = new_id()
    secret = TOKEN_PREFIX + secrets.token_urlsafe(32)
    now = utcnow()
    created, expires = iso(now), iso(now + timedelta(days=days))
    conn.execute(
        text(
            "INSERT INTO tokens (id, name, scopes, secret_hash, created_at, expires_at) "
            "VALUES (:id, :name, :scopes, :hash, :at, :exp)"
        ),
        {
            "id": token_id,
            "name": name,
            "scopes": " ".join(expanded),
            "hash": hash_secret(secret),
            "at": created,
            "exp": expires,
        },
    )
    audit(conn, by, "token.create", f"token:{token_id}", "ok")
    return TokenInfo(token_id, name, tuple(expanded), created, None, None, expires), secret


def get(conn: Connection, token_id: str) -> TokenInfo | None:
    row = conn.execute(text("SELECT * FROM tokens WHERE id = :id"), {"id": token_id}).fetchone()
    return _row(row) if row else None


def rotate(
    conn: Connection, token_id: str, by: str, *, days: int | None = None
) -> tuple[TokenInfo, str] | None:
    """Nouveau secret, mêmes nom et portées ; l'ancien jeton est révoqué. Sans `days`, la même
    durée de vie que l'ancien. None : jeton inconnu ou déjà révoqué."""
    old = get(conn, token_id)
    if old is None or old.revoked_at:
        return None
    if days is None:
        lived = parse_iso(old.expires_at) - parse_iso(old.created_at)
        days = max(1, min(MAX_DAYS, round(lived.total_seconds() / 86_400)))
    new = create(conn, old.name, list(old.scopes), by, days=days)
    revoke(conn, token_id, by)
    audit(conn, by, "token.rotate", f"token:{token_id}", new[0].id)
    return new


def expiring(conn: Connection, within_days: int = WARN_DAYS) -> list[TokenInfo]:
    """Les jetons actifs qui finissent dans `within_days` jours (ou ont fini) et dont l'alerte
    n'est pas encore partie ; ils sont marqués prévenus."""
    limit = iso(utcnow() + timedelta(days=within_days))
    rows = conn.execute(
        text(
            "SELECT * FROM tokens WHERE revoked_at IS NULL AND warned_at IS NULL "
            "AND expires_at <= :lim ORDER BY expires_at, id"
        ),
        {"lim": limit},
    ).fetchall()
    found = [_row(r) for r in rows]
    for t in found:
        conn.execute(
            text("UPDATE tokens SET warned_at = :at WHERE id = :id"), {"at": now_iso(), "id": t.id}
        )
    return found


def _row(r: Row[Any]) -> TokenInfo:
    m = r._mapping
    return TokenInfo(
        m["id"],
        m["name"],
        tuple(m["scopes"].split()),
        m["created_at"],
        m["last_used_at"],
        m["revoked_at"],
        m["expires_at"],
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
        text(
            "SELECT * FROM tokens WHERE secret_hash = :h AND revoked_at IS NULL "
            "AND expires_at > :now"
        ),
        {"h": hash_secret(secret), "now": now_iso()},
    ).fetchone()
    if row is None:
        return None
    conn.execute(
        text("UPDATE tokens SET last_used_at = :at WHERE id = :id"),
        {"at": now_iso(), "id": row._mapping["id"]},
    )
    return _row(row)
