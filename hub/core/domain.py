"""Contrat de domaine (spécification, section 5, revue d'architecture).

Le cœur découvre les domaines par un manifeste, sans aucun `if domain == …`. Un domaine
s'enregistre par le point d'entrée Python `hub.domains` ; les tests montent un domaine factice.
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


@dataclass(frozen=True)
class McpTool:
    name: str
    description: str
    input_schema: dict[str, Any]
    scope: str  # portée exigée, ex. 'finance:read'
    call: Callable[[dict[str, Any]], Any]


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
    db: str  # 'ok', 'missing', 'error'
    schema_version: int
    detail: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class Domain(Protocol):
    name: str
    schema_version: int
    scopes: frozenset[str]
    proposal_kinds: Mapping[str, ProposalKind]

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
