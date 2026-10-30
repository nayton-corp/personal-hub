"""Modèles des routes qui décrivent les domaines : outils de l'assistant (lot 7) et manifestes
(chantier S2)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from hub.api.schemas import ProfileOut

# --- outils de l'assistant (lot 7) ------------------------------------------------------------


class CapabilityOut(BaseModel):
    domain: str
    description: str
    instructions: str  # consignes du domaine pour l'assistant (manifeste)
    tools: list[str]
    aggregates_only: bool


class CapabilitiesOut(BaseModel):
    domains: list[CapabilityOut]
    profile: ProfileOut


class ToolOut(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any]


class ToolsOut(BaseModel):
    domain: str
    items: list[ToolOut]


class ToolCallOut(BaseModel):
    result: Any


# --- manifestes (S2) : ce que l'app monte pour chaque domaine actif -----------------------------


class TabOut(BaseModel):
    id: str
    label: str
    icon: str
    module: str
    order: int


class HomeCardOut(BaseModel):
    id: str
    label: str
    endpoint: str


class SettingsSectionOut(BaseModel):
    id: str
    label: str
    icon: str
    group: str
    module: str


class AppModuleOut(BaseModel):
    tabs: list[TabOut]
    home_cards: list[HomeCardOut]
    settings: list[SettingsSectionOut]
    cards: str | None
    home: str | None = None
    module: str | None = None


class ImporterOut(BaseModel):
    name: str
    label: str
    suffixes: list[str]


class DomainOut(BaseModel):
    name: str
    description: str
    schema_version: int
    app: AppModuleOut
    importers: list[ImporterOut]
    connectors: list[str]


class DomainListOut(BaseModel):
    items: list[DomainOut]
