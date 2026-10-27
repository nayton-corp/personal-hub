"""Modèles d'entrée et de sortie des routes du cœur."""

from __future__ import annotations

from typing import Any

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
