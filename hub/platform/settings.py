"""Réglages sans secret : fichier TOML (`HUB_SETTINGS`), surchargé par `HUB_<SECTION>__<CLÉ>`."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

DEFAULT_SETTINGS_FILE = Path("/etc/hub/settings.toml")


class Paths(BaseModel):
    data: Path = Path("/srv/hub/data")
    inbox: Path = Path("/srv/hub/inbox")
    archive: Path = Path("/srv/hub/archive")
    backup: Path = Path("/srv/hub/backup")

    def inbox_of(self, domain: str) -> Path:
        """Boîte d'entrée d'un domaine (chantier S4) : `hub watch-inbox` y range ce qu'il réclame
        et les collecteurs y déposent directement."""
        return self.inbox / domain

    def archive_of(self, domain: str) -> Path:
        return self.archive / domain


class Server(BaseModel):
    bind: str = "127.0.0.1:8710"
    public_origin: str = "http://localhost:8710"
    web_root: Path | None = None  # sert l'app depuis l'API (développement) ; Caddy en production

    @field_validator("public_origin")
    @classmethod
    def _origin(cls, v: str) -> str:
        parts = urlsplit(v)
        if (
            parts.scheme not in {"http", "https"}
            or not parts.hostname
            or parts.path not in {"", "/"}
        ):
            raise ValueError("public_origin doit être une origine, ex. https://hub.tailnet.ts.net")
        return v.rstrip("/")

    @property
    def host(self) -> str:
        return self.bind.rsplit(":", 1)[0]

    @property
    def port(self) -> int:
        return int(self.bind.rsplit(":", 1)[1])

    @property
    def rp_id(self) -> str:
        host = urlsplit(self.public_origin).hostname
        return host or "localhost"

    @property
    def secure(self) -> bool:
        return self.public_origin.startswith("https://")


class Auth(BaseModel):
    session_hours: int = Field(default=12, ge=1, le=24)
    bootstrap_minutes: int = Field(default=10, ge=1, le=60)
    challenge_seconds: int = Field(default=300, ge=30, le=900)
    rp_name: str = "Personal Hub"
    login_attempts_per_minute: int = 10
    # propositions qu'un jeton (un modèle) peut créer par heure glissante ; l'app n'a pas de limite
    token_proposals_per_hour: int = Field(default=60, ge=1, le=10_000)


class Notify(BaseModel):
    ntfy_url: str = "https://ntfy.sh"
    ntfy_topic_file: Path | None = None


class Backup(BaseModel):
    restic_local: Path | None = Path("/restic")  # dépôt restic sur le disque externe
    replica: Path | None = Path("/replica")  # réplique Litestream, sauvegardée elle aussi
    keep_local_days: int = Field(default=7, ge=1)


class Assistant(BaseModel):
    """L'assistant de la maison (assistant/), natif sur le Mac : l'orbe de l'app lui parle par
    le hub. Sans `url`, l'orbe reste grise et l'écran le dit."""

    url: str | None = None  # « http://host.docker.internal:8770 » depuis les conteneurs
    person: str | None = None  # la personne qui parle depuis l'app (la mémoire de l'assistant)


class Secrets(BaseModel):
    file: Path = Path("/etc/hub/secrets.enc.yaml")
    age_key_file: Path = Path("/run/secrets/age_key")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="HUB_", env_nested_delimiter="__", extra="allow", frozen=True
    )

    paths: Paths = Paths()
    server: Server = Server()
    auth: Auth = Auth()
    notify: Notify = Notify()
    secrets: Secrets = Secrets()
    backup: Backup = Backup()
    assistant: Assistant = Assistant()
    log_level: str = "INFO"
    domains: str = "*"  # HUB_DOMAINS : « * » tous, sinon « finance,agenda » ; vide : aucun

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        path = Path(os.environ.get("HUB_SETTINGS", DEFAULT_SETTINGS_FILE))
        sources: list[PydanticBaseSettingsSource] = [init_settings, env_settings]
        if path.is_file():
            sources.append(TomlConfigSettingsSource(settings_cls, toml_file=path))
        return tuple(sources)

    def domain(self, name: str) -> dict[str, Any]:
        """Section propre à un domaine (`[finance]`), lue par le domaine lui-même."""
        extra = self.model_extra or {}
        section = extra.get(name, {})
        return dict(section) if isinstance(section, dict) else {}

    def active_domains(self) -> frozenset[str] | None:
        """Les domaines à monter ; None : tous ceux qui sont installés."""
        return parse_domains(self.domains)

    def db_path(self, name: str) -> Path:
        return self.paths.data / f"{name}.db"


def parse_domains(value: str) -> frozenset[str] | None:
    if value.strip() == "*":
        return None
    return frozenset(n.strip() for n in value.split(",") if n.strip())


def env_domains() -> frozenset[str] | None:
    """`HUB_DOMAINS` lu sans les réglages complets (collecteurs, catalogue des connecteurs)."""
    return parse_domains(os.environ.get("HUB_DOMAINS", "*"))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
