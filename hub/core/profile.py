"""Profil de l'instance : un hub par personne (chantier « hub générique », G1).

Le profil vit dans `core.db` et se modifie depuis l'app ou par `hub profile set`. Le fuseau et
la devise de base ne s'y trouvent pas : ils servent aussi aux conteneurs qui n'ouvrent pas
`core.db` (collecteurs, planificateur) et viennent donc de `HUB_TZ` et `HUB_CURRENCY`, posés
par compose.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Connection, text
from sqlalchemy.exc import OperationalError

from hub.core.clock import local_tz, now_iso
from hub.core.coredb import audit
from hub.core.db import make_engine
from hub.core.money import base_currency
from hub.core.settings import Settings

_COUNTRY = re.compile(r"^[A-Z]{2}$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
DEFAULT_COUNTRY = "CH"
# modules ouverts par le pays de l'instance
COUNTRY_MODULES: dict[str, frozenset[str]] = {"CH": frozenset({"pillar3a"})}


class ProfileError(ValueError):
    pass


@dataclass(frozen=True)
class Profile:
    display_name: str | None
    country: str
    timezone: str

    @property
    def modules(self) -> frozenset[str]:
        return COUNTRY_MODULES.get(self.country, frozenset())

    def has(self, module: str) -> bool:
        return module in self.modules

    def public(self) -> dict[str, Any]:
        return {
            "display_name": self.display_name,
            "country": self.country,
            "timezone": self.timezone,
            "currency": base_currency(),
            "modules": sorted(self.modules),
        }


def default_country() -> str:
    """Pays d'une instance sans profil enregistré : `HUB_COUNTRY` (posé par `hub init` dans
    `deploy/.env`), CH sinon. Il choisit aussi le pack de règles d'une base finance neuve."""
    return clean_country(os.environ.get("HUB_COUNTRY") or DEFAULT_COUNTRY)


def default() -> Profile:
    return Profile(display_name=None, country=default_country(), timezone=local_tz().key)


def get(conn: Connection) -> Profile:
    row = conn.execute(text("SELECT display_name, country FROM profile WHERE id = 1")).first()
    if row is None:
        return default()
    return Profile(display_name=row[0], country=str(row[1]), timezone=local_tz().key)


def clean_name(value: str | None) -> str | None:
    if value is None:
        return None
    name = " ".join(value.split())
    if not name:
        return None
    if len(name) > 60 or _CONTROL.search(name):
        raise ProfileError("prénom : 60 caractères au plus, sans caractère de contrôle")
    return name


def clean_country(value: str) -> str:
    country = value.strip().upper()
    if not _COUNTRY.match(country):
        raise ProfileError("pays : code ISO à deux lettres, par exemple CH ou FR")
    return country


def update(
    conn: Connection,
    actor: str,
    *,
    display_name: str | None = None,
    country: str | None = None,
    clear_name: bool = False,
) -> Profile:
    """Change les champs donnés ; `clear_name` efface le prénom."""
    current = get(conn)
    name = None if clear_name else (clean_name(display_name) or current.display_name)
    country_code = clean_country(country) if country is not None else current.country
    conn.execute(
        text(
            "INSERT INTO profile (id, display_name, country, updated_at) "
            "VALUES (1, :n, :c, :at) ON CONFLICT (id) DO UPDATE SET "
            "display_name = excluded.display_name, country = excluded.country, "
            "updated_at = excluded.updated_at"
        ),
        {"n": name, "c": country_code, "at": now_iso()},
    )
    audit(conn, actor, "profile.update", None, "ok")
    return get(conn)


def load(settings: Settings) -> Profile:
    """Pour un domaine, qui n'a que ses réglages : lit `core.db`, ou le profil par défaut si
    la base n'existe pas encore (tests d'un domaine seul, premier démarrage)."""
    path = settings.db_path("core")
    if not path.exists():
        return default()
    engine = make_engine(path)
    try:
        with engine.connect() as conn:
            return get(conn)
    except OperationalError:  # core.db pas encore migrée
        return default()
    finally:
        engine.dispose()
