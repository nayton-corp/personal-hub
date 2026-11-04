"""Schémas des passkeys : inscription, connexion, session, retrait sous Face ID (audit M16)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ConfirmIn(BaseModel):
    """Une passkey existante qui signe le geste (défi `confirm`)."""

    model_config = ConfigDict(extra="forbid")
    challenge_id: str
    credential: dict[str, Any]


class RegisterBeginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bootstrap_code: str | None = Field(default=None, max_length=40)
    confirm: ConfirmIn | None = None  # requis depuis une session : Face ID d'une passkey en place


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
