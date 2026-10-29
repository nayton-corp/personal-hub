"""Contrat de domaine (spécification, section 5, revue d'architecture).

Le cœur découvre les domaines par un manifeste (`hub.core.manifest`), sans aucun
`if domain == …`. Un domaine s'enregistre par le point d'entrée Python `hub.domains` ;
`HUB_DOMAINS` choisit ceux qu'une instance monte. Les tests montent un domaine factice.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Literal, Protocol, runtime_checkable

import typer
from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import Connection, Engine

from hub.core.manifest import Manifest, Observation


@dataclass(frozen=True)
class Preview:
    summary: str  # « 42 écritures → Alimentation, octobre +318.40 CHF »
    details: dict[str, Any]  # ce que l'app affiche (liste tronquée, totaux)
    fingerprint: str  # sha256 hex de l'état lu


@dataclass(frozen=True)
class ExternalResult:
    status: Literal["ok", "failed", "unknown"]
    detail: dict[str, Any] = field(default_factory=dict)


class LocalHandler(Protocol):
    """Effet dans la base SQLite du domaine."""

    def preview(self, conn: Connection, params: BaseModel) -> Preview: ...

    def apply(self, conn: Connection, params: BaseModel, proposal_id: str) -> dict[str, Any]:
        """Appelé dans la transaction ouverte par le cœur ; n'ouvre ni ne valide de transaction."""
        ...


class AfterCommit(Protocol):
    """Facultatif sur un handler local : suite hors transaction, une fois l'effet validé
    (recalculs, relances). Une erreur y est journalisée, jamais remontée."""

    def after_commit(self, params: BaseModel, result: dict[str, Any]) -> None: ...


class ExternalHandler(Protocol):
    """Effet chez un tiers (Domia, calendrier) : appel idempotent."""

    def preview(self, params: BaseModel) -> Preview: ...

    def apply(self, params: BaseModel, idempotency_key: str) -> ExternalResult: ...

    def reconcile(self, proposal_id: str) -> ExternalResult: ...


Inverse = Callable[[dict[str, Any], dict[str, Any]], tuple[str, dict[str, Any]]]


@dataclass(frozen=True)
class ProposalKind:
    params_model: type[BaseModel]
    handler: LocalHandler | ExternalHandler
    ttl: timedelta = timedelta(hours=24)
    reversible: bool = False
    inverse: Inverse | None = None  # (params, result) -> (kind, params) qui annule
    ai_allowed: bool = False  # la portée <domaine>:propose peut-elle le créer ?
    external: bool = False  # vrai pour un ExternalHandler (le Protocol n'est pas discriminant)

    def __post_init__(self) -> None:
        if self.reversible and self.inverse is None:
            raise ValueError("un type réversible doit fournir son inverse")


class ToolCaller(Protocol):
    """Ce qu'un outil MCP voit de son appelant : ses portées, et les seuls effets permis à un
    modèle (créer une proposition, en lire l'état). Fourni par le cœur à chaque appel."""

    @property
    def actor(self) -> str: ...

    def allows(self, scope: str) -> bool: ...

    def propose(
        self, kind: str, params: dict[str, Any], reason: str | None = None
    ) -> dict[str, Any]: ...

    def proposal(self, proposal_id: str) -> dict[str, Any] | None: ...

    def collectors(self) -> list[dict[str, Any]]:
        """État des collecteurs (mode, échecs consécutifs, dernier résultat), sans contenu."""
        ...


@dataclass(frozen=True)
class McpTool:
    """Outil pour l'assistant (lot 7). Une portée `<domaine>:aggregates` est aussi ouverte à
    `<domaine>:read`. `call` reçoit des arguments déjà validés contre `input_schema` par le
    domaine lui-même et renvoie du JSON (montants en texte, jamais de flottant)."""

    name: str
    description: str
    input_schema: dict[str, Any]
    scope: str  # portée exigée, ex. 'finance:read'
    call: Callable[[dict[str, Any], ToolCaller], Any]


@dataclass(frozen=True)
class Hit:
    urn: str
    title: str
    date: str | None
    score: int  # plus grand = plus pertinent ; entier, pas de flottant


@dataclass(frozen=True)
class Ref:
    urn: str
    title: str
    date: str | None
    href: str


@dataclass(frozen=True)
class Event:
    seq: int
    type: str
    urn: str
    payload: dict[str, Any]
    created_at: str


@dataclass(frozen=True)
class Health:
    ok: bool
    db: str  # 'ok', 'missing', 'outdated', 'error' ou un écart propre au domaine
    schema_version: int
    detail: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class Domain(Protocol):
    name: str
    description: str  # une phrase pour l'app et l'assistant
    schema_version: int
    scopes: frozenset[str]
    proposal_kinds: Mapping[str, ProposalKind]

    def manifest(self) -> Manifest:
        """Ce que le domaine apporte à l'app, à la boîte d'entrée et à l'assistant (S2)."""
        ...

    def observations(self, limit: int) -> list[Observation]:
        """Constats récents, les plus récents d'abord (budget dépassé, abonnement en hausse)."""
        ...

    def process_inbox(self) -> dict[str, int]:
        """Traite ce qui attend dans `inbox/<domaine>/` (S4) ; compteurs seulement."""
        ...

    def engine(self) -> Engine:
        """Base SQLite du domaine (les effets locaux s'y appliquent)."""
        ...

    def migrate(self) -> None: ...

    def router(self) -> APIRouter: ...

    def cli(self) -> typer.Typer | None:
        """Sous-commandes `hub <domaine> …` (ex. `hub finance verify-ledger`)."""
        ...

    def mcp_tools(self) -> list[McpTool]: ...

    def search(self, q: str, limit: int, scopes: frozenset[str]) -> list[Hit]: ...

    def resolve(self, urn: str) -> Ref | None: ...

    def events_since(self, cursor: int, limit: int) -> list[Event]: ...

    def applied(self, proposal_ids: Sequence[str]) -> Mapping[str, dict[str, Any]]:
        """Lit `applied_proposals` : ce qui fait foi pour la réconciliation."""
        ...

    def record_applied(
        self, conn: Connection, proposal_id: str, kind: str, result: dict[str, Any]
    ) -> None:
        """Inscrit l'effet dans `applied_proposals` (et l'événement `proposal.applied`), dans la
        transaction de l'effet. La clé primaire interdit une seconde application."""
        ...

    def nightly(self) -> None: ...

    def health(self) -> Health:
        """Contrôle léger, appelé par /api/health."""
        ...

    def verify(self) -> Health:
        """Contrôle profond (`hub verify`, avant et après chaque migration) : verify-ledger."""
        ...
