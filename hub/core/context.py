"""Ce que l'API et la CLI partagent : réglages, `core.db`, registre des domaines."""

from __future__ import annotations

from dataclasses import dataclass

from hub.core.coredb import CoreDB
from hub.core.registry import Registry
from hub.core.settings import Settings


@dataclass
class HubContext:
    settings: Settings
    core: CoreDB
    registry: Registry

    @classmethod
    def build(cls, settings: Settings, registry: Registry | None = None) -> HubContext:
        return cls(
            settings=settings,
            core=CoreDB.from_settings(settings),
            registry=registry if registry is not None else Registry.discover(settings),
        )

    def migrate_all(self) -> None:
        self.core.migrate()
        for domain in self.registry:
            domain.migrate()

    def dispose(self) -> None:
        self.core.dispose()
        for domain in self.registry:
            domain.engine().dispose()
