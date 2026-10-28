"""Modèles d'entrée et de sortie des routes du cœur."""

from __future__ import annotations

from typing import Any, Literal

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
    name: str
    label: str
    mode: str
    consecutive_failures: int
    since: str
    check_requested: bool
    last_run: CollectorRunOut | None
    last_success_at: str | None
    can_enable: bool


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


class ConnectorListOut(BaseModel):
    items: list[ConnectorOut]


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
