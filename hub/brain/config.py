"""Réglages du brain : section `[brain]` de settings.toml, jetons dans le fichier de secrets."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from hub.core import secrets
from hub.core.settings import Settings

TokenName = Literal["brain", "aggregates"]


class BrainConfig(BaseModel):
    api_url: str = "http://api:8710"  # réseau compose « hub »
    # Ollama tourne en natif sur le Mac (GPU) ; MLX : http://host.docker.internal:8080/v1
    llm_url: str = "http://host.docker.internal:11434/v1"
    model: str = "qwen3:32b"
    timeout: int = Field(default=300, ge=10, le=3600)
    max_steps: int = Field(default=8, ge=1, le=20)  # appels d'outils par question
    suggest_groups: int = Field(default=5, ge=1, le=20)  # commerçants par passage
    suggest_entries: int = Field(default=10, ge=1, le=50)  # écritures par commerçant
    state_dir: Path = Path("/srv/hub/brain")


def config(settings: Settings) -> BrainConfig:
    return BrainConfig.model_validate(settings.domain("brain"))


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
