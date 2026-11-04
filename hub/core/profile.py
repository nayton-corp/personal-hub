"""Profil de l'instance : un hub par personne (chantier « hub générique », G1).

Le profil vit dans `core.db` et se modifie depuis l'app ou par `hub profile set`. Le fuseau, la
devise de base et la locale ne s'y trouvent pas : ils servent aussi aux conteneurs qui n'ouvrent
pas `core.db` (collecteurs, planificateur) et viennent donc de `HUB_TZ`, `HUB_CURRENCY` et
`HUB_LOCALE`, posés par compose. Ce que le cœur sait d'un pays, les domaines le lui apportent
par le point d'entrée `hub.country_packs` (audit M17) : le cœur ne nomme aucun pays.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from functools import cache
from typing import Any

from sqlalchemy import Connection, text
from sqlalchemy.exc import OperationalError

from hub.core.coredb import audit
from hub.core.registry import contributions_by_domain
from hub.kernel.clock import local_tz, now_iso
from hub.kernel.money import base_currency, exponent
from hub.platform.db import make_engine
from hub.platform.settings import Settings

_COUNTRY = re.compile(r"^[A-Z]{2}$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
DEFAULT_LOCALE = "fr"  # l'app est en français ; le pack pays précise la région
UNKNOWN_COUNTRY = "ZZ"  # code ISO réservé : aucun domaine installé ne connaît de pays


@cache
def country_packs() -> dict[str, dict[str, dict[str, Any]]]:
    """Domaine → pays → ce que le domaine sait du pays (`hub.country_packs`) : `modules`,
    `locale`, `currency` et `timezone` proposés à l'installation, `public` pour les clients."""
    return {
        domain: dict(table)
        for domain, table in contributions_by_domain("hub.country_packs").items()
    }


def known_countries() -> list[str]:
    return sorted({c for table in country_packs().values() for c in table})


def country_modules() -> dict[str, frozenset[str]]:
    """Pays → modules qu'il ouvre, tous domaines confondus."""
    out: dict[str, frozenset[str]] = {}
    for table in country_packs().values():
        for country, pack in table.items():
            out[country] = out.get(country, frozenset()) | frozenset(pack.get("modules") or ())
    return out


def country_defaults(country: str) -> dict[str, str | None]:
    """Locale, devise et fuseau que les packs proposent pour le pays (le premier domaine qui
    sait répond) ; None quand aucun ne le connaît."""
    out: dict[str, str | None] = {"locale": None, "currency": None, "timezone": None}
    for table in country_packs().values():
        pack = table.get(country) or {}
        for key in out:
            out[key] = out[key] or pack.get(key)
    return out


def country_public(country: str) -> dict[str, dict[str, Any]]:
    """Domaine → données publiques du pack du pays (consignes de l'IA…)."""
    return {
        domain: dict(table[country].get("public") or {})
        for domain, table in country_packs().items()
        if country in table
    }


class ProfileError(ValueError):
    pass


@dataclass(frozen=True)
class Profile:
    display_name: str | None
    country: str
    timezone: str

    @property
    def modules(self) -> frozenset[str]:
        return country_modules().get(self.country, frozenset())

    @property
    def locale(self) -> str:
        """Mise en forme des dates et des nombres : `HUB_LOCALE` (compose), sinon celle du pack
        du pays, sinon le français."""
        return (
            os.environ.get("HUB_LOCALE")
            or country_defaults(self.country)["locale"]
            or DEFAULT_LOCALE
        )

    def has(self, module: str) -> bool:
        return module in self.modules

    def public(self) -> dict[str, Any]:
        return {
            "display_name": self.display_name,
            "country": self.country,
            "timezone": self.timezone,
            "locale": self.locale,
            "currency": base_currency(),
            "currency_exponent": exponent(base_currency()),
            "modules": sorted(self.modules),
            "packs": country_public(self.country),
        }


def default_country() -> str:
    """Pays d'une instance sans profil enregistré : `HUB_COUNTRY` (posé par `hub init` dans
    `deploy/.env`), sinon le premier pays qu'un domaine installé connaît. Il choisit aussi le
    pack de règles d'une base finance neuve."""
    env = os.environ.get("HUB_COUNTRY")
    if env:
        return clean_country(env)
    return next(iter(known_countries()), UNKNOWN_COUNTRY)


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
