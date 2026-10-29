"""Registre des domaines, alimenté par le point d'entrée `hub.domains` et filtré par
`HUB_DOMAINS` ; les autres points d'entrée (`hub.connectors`, `hub.country_modules`,
`hub.connection_imports`) portent ce qu'un domaine apporte au cœur sans être monté."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from importlib.metadata import entry_points
from typing import Any

from hub.core.domain import Domain
from hub.core.errors import Problem
from hub.platform.settings import Settings, env_domains

ENTRY_POINT_GROUP = "hub.domains"
DomainFactory = Callable[[Settings], Domain]
# écrans et rubriques de la coquille de l'app : un domaine ne les reprend pas (S5)
SHELL_IDS = frozenset({"accueil", "sources", "display", "profile", "security", "health"})


def _screens(domain: Domain) -> list[str]:
    """Les identifiants qu'un domaine occupe dans l'app : onglets et rubriques des réglages."""
    app = domain.manifest().app
    return [t.id for t in app.tabs] + [s.id for s in app.settings]


class Registry:
    def __init__(self, domains: Iterable[Domain] = ()) -> None:
        self._domains: dict[str, Domain] = {}
        for d in domains:
            self.add(d)

    def add(self, domain: Domain) -> None:
        if not isinstance(domain, Domain):
            raise TypeError(f"{domain!r} ne respecte pas le contrat de domaine")
        if domain.name in self._domains or domain.name == "core":
            raise ValueError(f"domaine déjà enregistré : {domain.name}")
        for scope in domain.scopes:
            if not scope.startswith(f"{domain.name}:"):
                raise ValueError(f"portée {scope!r} hors du domaine {domain.name}")
        problems = domain.manifest().problems()
        taken = SHELL_IDS | {x for d in self for x in _screens(d)}
        problems += [f"écran déjà pris : {x}" for x in sorted(set(_screens(domain)) & taken)]
        if problems:
            raise ValueError(f"manifeste de {domain.name} : {', '.join(problems)}")
        self._domains[domain.name] = domain

    def __iter__(self) -> Iterator[Domain]:
        return iter(self._domains.values())

    def __len__(self) -> int:
        return len(self._domains)

    def names(self) -> list[str]:
        return sorted(self._domains)

    def get(self, name: str) -> Domain:
        try:
            return self._domains[name]
        except KeyError:
            raise Problem("domain.unknown", f"domaine inconnu : {name}") from None

    def all_scopes(self) -> frozenset[str]:
        return frozenset(s for d in self for s in d.scopes)

    def claimant(self, name: str, head: bytes) -> str | None:
        """Le domaine qui réclame un fichier de la boîte d'entrée ; aucun, ou plusieurs : None
        (le fichier attend qu'on le range)."""
        found = {d.name for d in self for i in d.manifest().importers if i.wants(name, head)}
        return found.pop() if len(found) == 1 else None

    @classmethod
    def discover(cls, settings: Settings) -> Registry:
        """Les domaines installés que `HUB_DOMAINS` retient ; un nom sans domaine installé est
        une faute de frappe, refusée au démarrage."""
        wanted = settings.active_domains()
        found = sorted(entry_points(group=ENTRY_POINT_GROUP), key=lambda e: e.name)
        unknown = sorted((wanted or set()) - {ep.name for ep in found})
        if unknown:
            raise ValueError(f"HUB_DOMAINS : domaine non installé : {', '.join(unknown)}")
        registry = cls()
        for ep in found:
            if wanted is None or ep.name in wanted:
                factory: DomainFactory = ep.load()
                registry.add(factory(settings))
        return registry


def contributions_by_domain(group: str) -> dict[str, Any]:
    """Les valeurs déclarées au point d'entrée `group` par les domaines que `HUB_DOMAINS`
    retient, par nom de domaine (le nom du point d'entrée) : le cœur les lit sans importer un
    domaine."""
    wanted = env_domains()
    return {
        ep.name: ep.load()
        for ep in sorted(entry_points(group=group), key=lambda e: e.name)
        if wanted is None or ep.name in wanted
    }


def contributions(group: str) -> list[Any]:
    return list(contributions_by_domain(group).values())
