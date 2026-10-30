"""Manifeste d'un domaine, v2 (chantier S2) : ce qu'il apporte au hub, déclaré une fois.

Le cœur, l'app et l'assistant lisent le manifeste au lieu de connaître le domaine :
- `app` : ses onglets, ses cartes d'accueil, ses rubriques de réglages et ses modules (cartes à
  valider, blocs de l'accueil, module du domaine), que la coquille de l'app monte (S5) ;
- `importers` : les fichiers de la boîte d'entrée qu'il réclame (S4 les lui confie) ;
- `connectors` : les entrées du catalogue qui le nourrissent (le catalogue lui-même arrive par
  le point d'entrée `hub.connectors`, lisible sans monter le domaine, voir D-016) ;
- `protected_tables` : ses tables en ajout seul, que `hub verify` contrôle ;
- `assistant` : ses consignes pour l'assistant, données avec ses outils (`hub_capabilities`).

Les constats (`Domain.observations`) restent une méthode : ils se calculent.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from sqlalchemy import Connection, text

ID = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
MODULE = re.compile(r"^[a-z][a-z0-9_-]{0,31}\.js$")  # fichier du dossier `web`, sans sous-dossier
SUFFIX = re.compile(r"^\.[a-z0-9]{1,8}$")
Severity = Literal["info", "warning", "alert"]


@dataclass(frozen=True)
class Tab:
    """Un onglet de la barre du bas : `module` exporte `render` et `actions`."""

    id: str
    label: str
    icon: str
    module: str
    order: int = 50  # l'accueil de la coquille vient avant (0), les réglages après


@dataclass(frozen=True)
class HomeCard:
    """Un bloc de l'accueil, lu sur `endpoint` (chemin sous /api/<domaine>)."""

    id: str
    label: str
    endpoint: str


@dataclass(frozen=True)
class SettingsSection:
    """Une rubrique de « Sources et réglages », dans la section de son domaine ; `group` (Données,
    Préférences) l'y ordonne."""

    id: str
    label: str
    icon: str
    group: str
    module: str


@dataclass(frozen=True)
class AppModule:
    tabs: tuple[Tab, ...] = ()
    home_cards: tuple[HomeCard, ...] = ()
    settings: tuple[SettingsSection, ...] = ()
    cards: str | None = None  # module qui dessine les cartes à valider du domaine
    home: str | None = None  # module qui ajoute ses blocs à l'accueil de la coquille
    module: str | None = None  # module du domaine : démarrage, rendu commun, liens (S5)
    web: Path | None = None  # le dossier de ses modules, servi sous /d/<domaine>/


@dataclass(frozen=True)
class Importer:
    """Des fichiers de la boîte d'entrée. `claims(nom, début du fichier)` affine le choix quand
    l'extension ne suffit pas ; sans lui, l'extension décide."""

    name: str
    label: str
    suffixes: frozenset[str]
    claims: Callable[[str, bytes], bool] | None = None

    def wants(self, name: str, head: bytes) -> bool:
        suffix = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
        if suffix not in self.suffixes:
            return False
        return self.claims(name, head) if self.claims is not None else True


@dataclass(frozen=True)
class Observation:
    """Un constat : ce qu'un domaine remarque seul (budget dépassé, document à renouveler).
    `title` nomme la chose, jamais un montant ; `detail` reste au niveau des agrégats."""

    key: str
    kind: str
    severity: Severity
    title: str
    on_date: str
    urn: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Manifest:
    description: str
    app: AppModule = AppModule()
    importers: tuple[Importer, ...] = ()
    connectors: tuple[str, ...] = ()
    protected_tables: frozenset[str] = frozenset()
    assistant: str = ""

    def problems(self) -> list[str]:
        """Ce qui empêche le registre d'accepter le manifeste (vide : accepté)."""
        out: list[str] = []
        if not self.description.strip():
            out.append("description vide")
        groups = [
            [t.id for t in self.app.tabs],
            [s.id for s in self.app.settings],
            [c.id for c in self.app.home_cards],
            [i.name for i in self.importers],
        ]
        for ids in groups:  # un identifiant est unique dans sa liste
            out += [f"identifiant invalide : {i!r}" for i in ids if not ID.match(i)]
            out += [f"identifiant en double : {i}" for i in sorted(set(ids)) if ids.count(i) > 1]
        modules = [t.module for t in self.app.tabs] + [s.module for s in self.app.settings]
        modules += [m for m in (self.app.cards, self.app.home, self.app.module) if m]
        out += [f"module invalide : {m!r}" for m in modules if not MODULE.match(m)]
        if modules and self.app.web is None:
            out.append("modules sans dossier web")
        out += [
            f"chemin invalide : {c.endpoint!r}"
            for c in self.app.home_cards
            if not c.endpoint.startswith("/") or ".." in c.endpoint
        ]
        suffixes = [s for i in self.importers for s in i.suffixes]
        out += [f"extension invalide : {s!r}" for s in suffixes if not SUFFIX.match(s)]
        out += [f"table invalide : {t!r}" for t in self.protected_tables if not ID.match(t)]
        return out

    def public(self) -> dict[str, Any]:
        """Vue de l'app et de l'assistant : tout sauf le code (`claims`)."""
        return {
            "description": self.description,
            "app": {
                "tabs": [vars(t) for t in sorted(self.app.tabs, key=lambda t: (t.order, t.id))],
                "home_cards": [vars(c) for c in self.app.home_cards],
                "settings": [vars(s) for s in self.app.settings],
                "cards": self.app.cards,
                "home": self.app.home,
                "module": self.app.module,
            },
            "importers": [
                {"name": i.name, "label": i.label, "suffixes": sorted(i.suffixes)}
                for i in self.importers
            ],
            "connectors": list(self.connectors),
        }


def unguarded(conn: Connection, tables: Iterable[str]) -> list[str]:
    """Les tables protégées qu'un trigger n'empêche pas de modifier ou d'effacer."""
    rows = conn.execute(
        text("SELECT tbl_name, upper(sql) FROM sqlite_master WHERE type = 'trigger'")
    ).fetchall()
    out = []
    for table in sorted(tables):
        sql = [s for t, s in rows if t == table and "RAISE(ABORT" in s]
        if not all(any(f"BEFORE {verb} ON" in s for s in sql) for verb in ("UPDATE", "DELETE")):
            out.append(table)
    return out
