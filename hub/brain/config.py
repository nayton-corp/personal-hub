"""Réglages du brain : section `[brain]` de settings.toml, jetons dans le fichier de secrets."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from hub.platform import secrets
from hub.platform.settings import Settings

TokenName = Literal["brain", "aggregates"]


class BrainConfig(BaseModel):
    """En natif sur le Mac depuis S10 (plus de conteneur) : la section `[brain]` du fichier de
    réglages que nomme `HUB_SETTINGS`. Le classement du matin passe par l'assistant
    (`python -m domia_assistant classify`) ; `hub-brain` reste pour les gestes à la main."""

    api_url: str = "http://127.0.0.1:8710"  # `make dev` ; sur le Mac : https://hub.<tailnet>.ts.net
    # Ollama tourne en natif sur le Mac (GPU) ; MLX : http://127.0.0.1:8080/v1
    llm_url: str = "http://127.0.0.1:11434/v1"
    model: str = "qwen3:32b"
    timeout: int = Field(default=300, ge=10, le=3600)
    max_steps: int = Field(default=8, ge=1, le=20)  # appels d'outils par question
    suggest_groups: int = Field(default=5, ge=1, le=20)  # commerçants par passage
    suggest_entries: int = Field(default=10, ge=1, le=50)  # écritures par commerçant
    state_dir: Path = Path.home() / "PersonalHub" / "brain"


def config(settings: Settings) -> BrainConfig:
    """`HUB_BRAIN_MODEL` remplace le modèle du fichier de réglages, le temps d'un essai."""
    data = settings.domain("brain")
    model = os.environ.get("HUB_BRAIN_MODEL", "").strip()
    if model:
        data["model"] = model
    return BrainConfig.model_validate(data)


class TokenMissing(RuntimeError):
    pass


def token(settings: Settings, name: TokenName) -> str:
    """Jeton `brain` ou `aggregates` de la section `brain` du fichier de secrets."""
    try:
        section = secrets.section(settings.secrets.file, settings.secrets.age_key_file, "brain")
    except secrets.SecretsError as exc:
        raise TokenMissing(f"secrets illisibles : {exc}") from None
    value = section.get(name)
    if not isinstance(value, str) or not value:
        raise TokenMissing(f"jeton « {name} » absent de la section brain des secrets")
    return value
