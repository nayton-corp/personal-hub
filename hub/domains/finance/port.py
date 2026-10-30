"""Ce que les bords de la finance (routes, commandes, outils, propositions, reconstruction)
attendent du domaine : `FinanceDomain` le remplit, et ces modules ne l'importent pas. Chaque
sous-contexte déclare de son côté le peu qu'il en utilise (son `Host`)."""

from __future__ import annotations

from datetime import date
from typing import Any, Protocol

from hub.domains.finance.patrimoine.app.snapshots import Refresh
from hub.domains.finance.registre.app.ledger import VerifyResult
from hub.domains.finance.registre.interface.terminal import Host
from hub.domains.finance.sources.app.importer import ImportService


class Finance(Host, Protocol):
    importer: ImportService

    def today(self) -> date: ...

    def pillar3a(self) -> dict[str, Any]: ...

    def verify_ledger(self) -> VerifyResult: ...

    def refresh_snapshots(self, *, force: bool = False) -> Refresh: ...

    def refresh_derived(self) -> dict[str, int]: ...

    def migrate(self, *, seed: bool = True) -> None: ...
