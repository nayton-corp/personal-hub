"""Connexions de l'instance (chantier « hub générique », G4).

Une connexion est l'usage d'un connecteur du catalogue : un identifiant, un horaire, des
réglages sans secret et des secrets. Les secrets arrivent en clair (app ou terminal), sont
chiffrés par age vers la clé de la machine et ne sont plus jamais relus par l'API : seul le
service collecteur qui exécute la connexion (`collector-api` ou `collector-browser`) les
déchiffre, au moment du run.
"""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Connection as Db
from sqlalchemy import text

from hub.core import connectors
from hub.core.coredb import audit
from hub.core.errors import Problem
from hub.kernel.clock import now_iso
from hub.platform import cron, secrets

ID = re.compile(r"^[a-z][a-z0-9-]{1,39}$")
RESERVED = frozenset({"catalog", "connections", "refresh", "runner"})  # segments de route
MAX_SETTINGS = 16_384
MAX_SECRETS = 65_536
_COLUMNS = "id, connector, label, schedule, settings, secrets, secrets_at, created_at, updated_at"


@dataclass(frozen=True)
class Connection:
    id: str
    connector: str
    label: str
    schedule: str | None  # None : horaire du catalogue
    settings: dict[str, Any]
    secrets: bytes | None  # JSON chiffré age
    secrets_at: str | None
    created_at: str
    updated_at: str

    @property
    def spec(self) -> connectors.Connector | None:
        return connectors.get(self.connector)

    @property
    def effective_schedule(self) -> str | None:
        spec = self.spec
        return self.schedule or (spec.schedule if spec else None)

    @property
    def ready(self) -> bool:
        """Exécutable : ses secrets sont donnés, ou son connecteur n'en exige aucun."""
        spec = self.spec
        return spec is not None and (self.secrets is not None or not spec.secrets)

    def public(self) -> dict[str, Any]:
        """Vue de l'app : jamais les secrets, seulement s'ils sont donnés."""
        spec = self.spec
        return {
            "id": self.id,
            "connector": self.connector,
            "label": self.label,
            "method": spec.method if spec else None,
            "runner": spec.runner if spec else None,
            "schedule": self.effective_schedule,
            "custom_schedule": self.schedule is not None,
            "settings": self.settings,
            "secret_fields": list(spec.secrets) if spec else [],
            "has_secrets": self.secrets is not None,
            "secrets_at": self.secrets_at,
            "ready": self.ready,
        }

    def for_runner(self) -> dict[str, Any]:
        """Vue du service collecteur : les secrets restent chiffrés (base64 du fichier age)."""
        return {
            "id": self.id,
            "connector": self.connector,
            "label": self.label,
            "schedule": self.effective_schedule,
            "settings": self.settings,
            "secrets": base64.b64encode(self.secrets).decode() if self.secrets else None,
        }


def _row(r: Any) -> Connection:
    return Connection(
        r.id,
        r.connector,
        r.label,
        r.schedule,
        json.loads(r.settings or "{}"),
        bytes(r.secrets) if r.secrets is not None else None,
        r.secrets_at,
        r.created_at,
        r.updated_at,
    )


def _order(c: Connection) -> tuple[int, str]:
    names = connectors.names()
    return (names.index(c.connector) if c.connector in names else len(names), c.id)


def list_all(conn: Db) -> list[Connection]:
    rows = conn.execute(text(f"SELECT {_COLUMNS} FROM connections")).fetchall()  # noqa: S608
    return sorted((_row(r) for r in rows), key=_order)


def get(conn: Db, connection_id: str) -> Connection | None:
    row = conn.execute(
        text(f"SELECT {_COLUMNS} FROM connections WHERE id = :i"),  # noqa: S608 - colonnes fixes
        {"i": connection_id},
    ).first()
    return _row(row) if row else None


def require(conn: Db, connection_id: str) -> Connection:
    found = get(conn, connection_id)
    if found is None:
        raise Problem("collector.unknown")
    return found


def for_runner(conn: Db, runner: str) -> list[Connection]:
    """Les connexions exécutables d'un service collecteur."""
    return [c for c in list_all(conn) if c.ready and c.spec and c.spec.runner == runner]


# --- validation ---------------------------------------------------------------------------------


def clean_label(value: str) -> str:
    label = " ".join(value.split())
    if not 1 <= len(label) <= 60:
        raise Problem("validation.params", "nom : 1 à 60 caractères")
    return label


def clean_schedule(value: str) -> str:
    schedule = " ".join(value.split())
    try:
        jobs = cron.parse(f"{schedule} run")
    except ValueError as exc:
        raise Problem("validation.params", f"horaire : {exc}") from None
    if len(jobs) != 1 or len(schedule.split()) != 5:
        raise Problem("validation.params", "horaire : cinq champs cron, ex. 30 7 * * 1-5")
    return schedule


def clean_settings(spec: connectors.Connector, value: dict[str, Any]) -> dict[str, Any]:
    unknown = sorted(set(value) - set(spec.settings))
    if unknown:
        raise Problem("validation.params", f"réglages inconnus : {', '.join(unknown)}")
    if len(json.dumps(value)) > MAX_SETTINGS:
        raise Problem("validation.params", "réglages trop longs")
    return spec.clean(value) if spec.clean is not None else value


def _required(spec: connectors.Connector, value: dict[str, Any]) -> dict[str, Any]:
    missing = [k for k in spec.required if not value.get(k)]
    if missing:
        raise Problem("validation.params", f"réglages manquants : {', '.join(missing)}")
    return value


def _spec(connector: str) -> connectors.Connector:
    spec = connectors.get(connector)
    if spec is None:
        raise Problem("validation.params", f"connecteur inconnu : {connector}")
    return spec


# --- écriture -----------------------------------------------------------------------------------


def create(
    conn: Db,
    connection_id: str,
    connector: str,
    by: str,
    *,
    label: str | None = None,
    schedule: str | None = None,
    settings: dict[str, Any] | None = None,
) -> Connection:
    spec = _spec(connector)
    if not ID.match(connection_id) or connection_id in RESERVED:
        raise Problem("validation.params", "identifiant : minuscules, chiffres et tirets")
    if get(conn, connection_id) is not None:
        raise Problem("connection.exists")
    if spec.single:
        taken = conn.execute(
            text("SELECT id FROM connections WHERE connector = :c LIMIT 1"), {"c": connector}
        ).scalar()
        if taken:
            raise Problem(
                "connection.single",
                f"« {spec.label} » existe déjà ({taken}) : une seule connexion de ce type, "
                "elle se complète dans ses réglages",
                connection=taken,
            )
    at = now_iso()
    conn.execute(
        text(
            "INSERT INTO connections (id, connector, label, schedule, settings, created_at, "
            "updated_at) VALUES (:i, :c, :l, :s, :st, :at, :at)"
        ),
        {
            "i": connection_id,
            "c": connector,
            "l": clean_label(label or spec.label),
            "s": clean_schedule(schedule) if schedule else None,
            "st": json.dumps(_required(spec, clean_settings(spec, settings or {})), sort_keys=True),
            "at": at,
        },
    )
    audit(conn, by, "connection.create", f"connection:{connection_id}", "ok")
    return require(conn, connection_id)


def update(
    conn: Db,
    connection_id: str,
    by: str,
    *,
    label: str | None = None,
    schedule: str | None = None,
    default_schedule: bool = False,
    settings: dict[str, Any] | None = None,
) -> Connection:
    """Change les champs donnés ; `default_schedule` revient à l'horaire du catalogue."""
    current = require(conn, connection_id)
    spec = _spec(current.connector)
    new_schedule = (
        None
        if default_schedule
        else (clean_schedule(schedule) if schedule is not None else current.schedule)
    )
    conn.execute(
        text(
            "UPDATE connections SET label = :l, schedule = :s, settings = :st, updated_at = :at "
            "WHERE id = :i"
        ),
        {
            "i": connection_id,
            "l": clean_label(label) if label is not None else current.label,
            "s": new_schedule,
            "st": json.dumps(
                clean_settings(spec, settings) if settings is not None else current.settings,
                sort_keys=True,
            ),
            "at": now_iso(),
        },
    )
    audit(conn, by, "connection.update", f"connection:{connection_id}", "ok")
    return require(conn, connection_id)


def set_secrets(
    conn: Db, connection_id: str, values: dict[str, Any], recipient: str, by: str
) -> Connection:
    """Remplace tous les secrets d'une connexion (l'API ne peut pas les relire pour les
    compléter). Les champs exigés par le connecteur doivent être des textes non vides."""
    current = require(conn, connection_id)
    spec = _spec(current.connector)
    missing = [k for k in spec.secrets if not isinstance(values.get(k), str) or not values[k]]
    if missing:
        raise Problem("validation.params", f"secrets manquants : {', '.join(missing)}")
    if "token" in values:
        raise Problem("validation.params", "le jeton du service ne va pas dans une connexion")
    plain = json.dumps(values, sort_keys=True).encode()
    if len(plain) > MAX_SECRETS:
        raise Problem("validation.params", "secrets trop longs")
    at = now_iso()
    conn.execute(
        text(
            "UPDATE connections SET secrets = :b, secrets_at = :at, updated_at = :at WHERE id = :i"
        ),
        {"i": connection_id, "b": secrets.encrypt_for(recipient, plain), "at": at},
    )
    audit(conn, by, "connection.secrets", f"connection:{connection_id}", "ok")
    return require(conn, connection_id)


def clear_secrets(conn: Db, connection_id: str, by: str) -> Connection:
    require(conn, connection_id)
    conn.execute(
        text(
            "UPDATE connections SET secrets = NULL, secrets_at = NULL, updated_at = :at "
            "WHERE id = :i"
        ),
        {"i": connection_id, "at": now_iso()},
    )
    audit(conn, by, "connection.secrets_cleared", f"connection:{connection_id}", "ok")
    return require(conn, connection_id)


def delete(conn: Db, connection_id: str, by: str) -> None:
    """Retire la connexion et son état ; l'historique des runs reste."""
    require(conn, connection_id)
    conn.execute(text("DELETE FROM connections WHERE id = :i"), {"i": connection_id})
    conn.execute(text("DELETE FROM collector_state WHERE collector = :i"), {"i": connection_id})
    audit(conn, by, "connection.delete", f"connection:{connection_id}", "ok")
