"""Modèles d'entrée et de sortie des routes du cœur."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class DomainHealthOut(BaseModel):
    db: str
    schema_version: int
    ok: bool


class CoreHealthOut(BaseModel):
    db: str
    revision: str | None
    ok: bool


class HealthOut(BaseModel):
    status: str
    version: str
    core: CoreHealthOut
    domains: dict[str, DomainHealthOut]


class ProposalCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    domain: str = Field(min_length=1, max_length=40)
    kind: str = Field(min_length=1, max_length=60)
    params: dict[str, Any]
    reason: str | None = Field(default=None, max_length=500)
    bundle_id: str | None = Field(default=None, max_length=40)
    # un modèle déclare false quand la proposition ne vient pas d'un texte externe ; sinon
    # elle reste au palier human quelle que soit la politique
    external_text: bool | None = None


class PreviewOut(BaseModel):
    summary: str
    details: dict[str, Any]


class ProposalOut(BaseModel):
    id: str
    urn: str
    domain: str
    kind: str
    params: dict[str, Any]
    revision: int
    status: str
    tier: str
    preview: PreviewOut
    reason: str | None
    bundle_id: str | None
    created_by: str
    created_at: str
    expires_at: str
    decided_at: str | None
    result: dict[str, Any] | None


class ProposalListOut(BaseModel):
    items: list[ProposalOut]


class HitOut(BaseModel):
    domain: str
    urn: str
    title: str
    date: str | None


class SearchOut(BaseModel):
    items: list[HitOut]


class RefOut(BaseModel):
    urn: str
    title: str
    date: str | None
    href: str


class LinkOut(BaseModel):
    from_urn: str
    to_urn: str
    rel: str
    other: RefOut | None


class LinksOut(BaseModel):
    outgoing: list[LinkOut]
    incoming: list[LinkOut]


class RegisterBeginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bootstrap_code: str | None = Field(default=None, max_length=40)


class ChallengeOut(BaseModel):
    challenge_id: str
    options: dict[str, Any]


class RegisterFinishIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    challenge_id: str
    credential: dict[str, Any]
    device_name: str | None = Field(default=None, max_length=60)
    bootstrap_code: str | None = Field(default=None, max_length=40)


class LoginFinishIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    challenge_id: str
    credential: dict[str, Any]


class SessionOut(BaseModel):
    authenticated: bool
    actor: str | None = None
    expires_at: str | None = None
    passkeys: int
    needs_bootstrap: bool


class PasskeyOut(BaseModel):
    id: str
    device_name: str | None
    created_at: str
    last_used_at: str | None


class PasskeysOut(BaseModel):
    items: list[PasskeyOut]


class ApprovalChallengeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    proposal_ids: list[str] = Field(min_length=1, max_length=50)
    action: Literal["accept", "revert"] = "accept"


class ApprovalChallengeOut(BaseModel):
    challenge_id: str
    options: dict[str, Any]
    approval_digest: str


class AcceptIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    proposal_ids: list[str] = Field(min_length=1, max_length=50)
    challenge_id: str = Field(max_length=40)
    assertion: dict[str, Any]


class AcceptResultOut(BaseModel):
    id: str
    status: str
    result: dict[str, Any] | None = None
    problem: dict[str, Any] | None = None


class AcceptOut(BaseModel):
    results: list[AcceptResultOut]


class RevertIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    challenge_id: str = Field(max_length=40)
    assertion: dict[str, Any]


class DigestItemOut(ProposalOut):
    reversible: bool
    reverted_by: str | None


class DigestOut(BaseModel):
    day: str
    items: list[DigestItemOut]


# --- collecteurs (lot 5) ----------------------------------------------------------------------


class CollectorRunOut(BaseModel):
    id: str
    kind: str
    outcome: str
    started_at: str
    ended_at: str | None
    files: int
    detail: str | None


class CollectorOut(BaseModel):
    name: str  # identifiant de la connexion
    label: str
    connector: str
    ready: bool  # secrets donnés (ou aucun exigé) : le service collecteur l'exécute
    mode: str
    consecutive_failures: int
    since: str
    check_requested: bool
    run_requested: bool  # actualisation demandée depuis l'app, pas encore faite
    last_run: CollectorRunOut | None
    last_success_at: str | None
    can_enable: bool
    link_requested: bool  # consentement demandé depuis l'app, pas encore pris
    link_url: str | None  # adresse d'autorisation à ouvrir, quelques minutes


class CollectorListOut(BaseModel):
    items: list[CollectorOut]


class ConnectorOut(BaseModel):
    name: str
    label: str
    method: Literal["open_banking", "api", "public", "browser"]
    country: str | None
    accounts: list[str]
    secrets: list[str]
    schedule: str
    formats: list[str]
    settings: list[str]
    required_settings: list[str]
    runner: Literal["api", "browser"]


class ConnectorListOut(BaseModel):
    items: list[ConnectorOut]


# --- connexions (G4) : l'app les règle, les services collecteurs les exécutent ---------------

ConnectionId = Annotated[str, Field(pattern=r"^[a-z][a-z0-9-]{1,39}$")]


class ConnectionOut(BaseModel):
    id: str
    connector: str
    label: str
    method: str | None
    runner: str | None
    schedule: str | None
    custom_schedule: bool
    settings: dict[str, Any]
    secret_fields: list[str]
    has_secrets: bool
    secrets_at: str | None
    ready: bool


class ConnectionListOut(BaseModel):
    items: list[ConnectionOut]


class ConnectionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: ConnectionId
    connector: str = Field(max_length=40)
    label: str | None = Field(default=None, max_length=60)
    schedule: str | None = Field(default=None, max_length=100)
    settings: dict[str, Any] = {}


class ConnectionPatch(BaseModel):
    """Champs absents : inchangés ; `default_schedule` revient à l'horaire du catalogue."""

    model_config = ConfigDict(extra="forbid")
    label: str | None = Field(default=None, max_length=60)
    schedule: str | None = Field(default=None, max_length=100)
    default_schedule: bool = False
    settings: dict[str, Any] | None = None


class ConnectionSecretsIn(BaseModel):
    """Tous les secrets de la connexion, en clair sur la liaison TLS ; chiffrés aussitôt."""

    model_config = ConfigDict(extra="forbid")
    values: dict[str, Any]


class RunnerConnectionOut(BaseModel):
    id: str
    connector: str
    label: str
    schedule: str | None
    settings: dict[str, Any]
    secrets: str | None  # fichier age en base64, déchiffré par le service collecteur seul


class RunnerListOut(BaseModel):
    items: list[RunnerConnectionOut]


class CollectorRunsOut(BaseModel):
    items: list[CollectorRunOut]


class CollectorRunIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["run", "check"] = "run"
    outcome: Literal[
        "ok",
        "nothing_new",
        "auth_pending_timeout",
        "site_unavailable",
        "selector_missing",
        "invalid_file",
        "auth_error",
        "unknown",
    ]
    started_at: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")
    ended_at: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")
    files: int = Field(default=0, ge=0, le=1000)
    detail: str | None = Field(default=None, max_length=200)


class CollectorModeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["enabled", "disabled"]


class CollectorNotifyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event: Literal["auth_pending", "consent_expiring"]


class CollectorNotifyOut(BaseModel):
    sent: bool


class CollectorLinkIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    state: str = Field(min_length=16, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")


class CollectorLinkUrlIn(BaseModel):
    """Adresse d'autorisation ouverte par le collecteur ; nulle : liaison finie."""

    model_config = ConfigDict(extra="forbid")
    url: str | None = Field(default=None, max_length=4000)


class CollectorLinkOut(BaseModel):
    state: str
    expires_at: str | None = None
    code: str | None = None


# --- outils de l'assistant (lot 7) ------------------------------------------------------------


class CapabilityOut(BaseModel):
    domain: str
    description: str
    tools: list[str]
    aggregates_only: bool


class ProfileOut(BaseModel):
    display_name: str | None
    country: str
    timezone: str
    currency: str  # devise de base, HUB_CURRENCY
    modules: list[str]


class ProfileIn(BaseModel):
    """Champs absents : inchangés ; `display_name` vide : prénom effacé."""

    model_config = ConfigDict(extra="forbid")
    display_name: str | None = Field(default=None, max_length=60)
    country: str | None = Field(default=None, pattern=r"^[A-Za-z]{2}$")


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
