"""Connecteurs : la forme d'une source que le hub sait collecter (chantier « hub générique », G3).

Le cœur ne connaît aucune source : chaque domaine déclare les siennes au point d'entrée
`hub.connectors` (la finance : `hub.domains.finance.connectors:CATALOG`). Un connecteur donne son
nom, sa méthode, son pays, les types de comptes qu'il alimente, les champs de secrets qu'il
attend, les réglages qu'il accepte et son horaire par défaut. Une *connexion* (G4,
`connections` dans `core.db`) est l'usage d'un connecteur par l'instance : un identifiant, ses
secrets chiffrés, son horaire et ses réglages. Un même connecteur peut servir plusieurs
connexions.

Méthodes, par ordre de préférence : `open_banking` (agrégateur réglementé, consentement par
lien), `api` (API officielle du fournisseur, clé en lecture seule), `public` (données publiques,
sans compte), `browser` (robot qui télécharge l'export officiel, seulement sans autre accès).
Le dépôt manuel d'un fichier reste toujours possible, sans connecteur.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from functools import cache
from typing import Any, Literal

from hub.core.registry import contributions_by_domain

Method = Literal["open_banking", "api", "public", "browser"]
METHODS: tuple[Method, ...] = ("open_banking", "api", "public", "browser")
Runner = Literal["api", "browser"]
RUNNERS: tuple[Runner, ...] = ("api", "browser")
ENTRY_POINT_GROUP = "hub.connectors"
Clean = Callable[[dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class Connector:
    name: str
    label: str
    method: Method
    country: str | None  # ISO 3166-1, ou None pour un service international
    accounts: tuple[str, ...]  # types de comptes alimentés, au sens du domaine
    secrets: tuple[str, ...]  # champs obligatoires de la section `collector-<nom>`
    schedule: str  # horaire par défaut, fuseau de l'instance
    formats: tuple[str, ...]  # sources d'import des fichiers qu'il dépose (`imports.source`)
    settings: tuple[str, ...] = ()  # réglages sans secret qu'une connexion peut donner
    required: tuple[str, ...] = ()  # réglages qu'une nouvelle connexion doit donner
    single: bool = False  # une seule connexion possible (ses réglages portent tout)
    clean: Clean | None = None  # contrôle propre au connecteur, après celui des réglages connus
    domain: str = ""  # domaine qui l'a déclaré (nom du point d'entrée), posé par `catalog()`

    @property
    def runner(self) -> Runner:
        """Service collecteur qui l'exécute : les robots ont Chromium, les autres non."""
        return "browser" if self.method == "browser" else "api"

    @property
    def link(self) -> bool:
        """Accès donné par un consentement, ouvert par un lien (open banking)."""
        return self.method == "open_banking"

    def public(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "method": self.method,
            "country": self.country,
            "accounts": list(self.accounts),
            "secrets": list(self.secrets),
            "schedule": self.schedule,
            "formats": list(self.formats),
            "settings": list(self.settings),
            "required_settings": list(self.required),
            "runner": self.runner,
            "single": self.single,
        }


@cache
def catalog() -> tuple[Connector, ...]:
    """Les connecteurs de tous les domaines installés, dans l'ordre des domaines puis du leur."""
    found = tuple(
        replace(c, domain=domain)
        for domain, group in contributions_by_domain(ENTRY_POINT_GROUP).items()
        for c in group
    )
    names = [c.name for c in found]
    if len(set(names)) != len(names):
        raise ValueError("deux connecteurs portent le même nom")
    return found


def names() -> tuple[str, ...]:
    return tuple(c.name for c in catalog())


def get(name: str) -> Connector | None:
    return next((c for c in catalog() if c.name == name), None)
