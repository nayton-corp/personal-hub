"""La nuit de la Finance en morceaux (contrat `NightlyTasks`) : chacun a sa ligne dans
Réglages › État des sources, son dernier passage et son bouton « Actualiser ». La nuit les lance
dans cet ordre ; un morceau dit ce qu'il a fait en quelques mots, jamais un montant."""

from __future__ import annotations

from typing import TYPE_CHECKING

from hub.core.domain import DomainTask

if TYPE_CHECKING:
    from hub.domains.finance.domain import FinanceDomain

COMPOSITIONS_CONNECTOR = "market"  # le collecteur des cours lit aussi les compositions des fonds


def _count(n: int, one: str, many: str, none: str = "rien de neuf") -> str:
    return none if n == 0 else f"{n} {one if n == 1 else many}"


def build(fin: FinanceDomain) -> tuple[DomainTask, ...]:
    def snapshots() -> str:
        fin.refresh_snapshots(force=True)
        return "courbe recalculée"

    def strategies() -> str:
        opened = len(fin.run_strategies())
        found = fin.detect_strategies()
        said = [
            _count(found, "DCA repéré", "DCA repérés", ""),
            _count(opened, "étape atteinte", "étapes atteintes", ""),
        ]
        return " · ".join(s for s in said if s) or "rien de neuf"

    def sentinels() -> str:
        return _count(len(fin.run_sentinels()), "alerte", "alertes")

    def reviews() -> str:
        return _count(
            fin.request_reviews(),
            "relevé à valider",
            "relevés à valider",
            "aucun relevé en attente",
        )

    def ledger() -> str:
        result = fin.verify_ledger()
        if not result.ok:
            raise RuntimeError("registre : chaîne d'empreintes en écart")
        return "intact"

    return (
        DomainTask("snapshots", "Courbe du patrimoine", snapshots),
        DomainTask("strategies", "Stratégies : étapes et DCA repérés", strategies),
        DomainTask("sentinels", "Alertes budget, abonnements, prévoyance", sentinels),
        DomainTask("reviews", "Cartes « À valider »", reviews),
        DomainTask(
            "compositions",
            "Compositions des fonds",
            connector=COMPOSITIONS_CONNECTOR,
            when="chaque jour avec les cours",
        ),
        DomainTask("ledger", "Contrôle du registre", ledger),
    )
