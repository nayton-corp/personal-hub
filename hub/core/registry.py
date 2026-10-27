"""Registre des domaines, alimenté par le point d'entrée `hub.domains`."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from importlib.metadata import entry_points

from hub.core.domain import Domain
from hub.core.errors import Problem
from hub.core.settings import Settings

ENTRY_POINT_GROUP = "hub.domains"
DomainFactory = Callable[[Settings], Domain]


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

    @classmethod
    def discover(cls, settings: Settings) -> Registry:
        registry = cls()
        for ep in sorted(entry_points(group=ENTRY_POINT_GROUP), key=lambda e: e.name):
            factory: DomainFactory = ep.load()
            registry.add(factory(settings))
        return registry
