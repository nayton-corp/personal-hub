"""Ce que tous les collecteurs partagent : résultats, échecs typés, réglages, mémoire locale."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from hub.core import secrets
from hub.core.settings import Settings

Outcome = Literal[
    "ok",
    "nothing_new",
    "auth_pending_timeout",
    "site_unavailable",
    "selector_missing",
    "invalid_file",
    "auth_error",
    "unknown",
]
Kind = Literal["run", "check"]
NAMES = ("bcf", "viac", "revolut")


class Failure(Exception):
    """Un run qui s'arrête : le type d'échec de la section 8 et l'étape (jamais de contenu)."""

    def __init__(self, outcome: Outcome, detail: str) -> None:
        super().__init__(f"{outcome}: {detail}")
        self.outcome = outcome
        self.detail = detail


@dataclass
class Result:
    outcome: Outcome
    files: int = 0
    detail: str | None = None


class RevolutConfig(BaseModel):
    aspsp_name: str = "Revolut"
    aspsp_country: str = "LT"  # clients suisses : Revolut Bank UAB (Lituanie), à confirmer
    psu_type: Literal["personal", "business"] = "personal"
    consent_days: int = Field(default=180, ge=1, le=730)
    max_syncs_per_day: int = Field(default=4, ge=1, le=4)  # limite Revolut sans l'utilisateur
    overlap_days: int = Field(default=10, ge=1, le=60)
    warn_days: int = Field(default=14, ge=1)  # alerte avant la fin du consentement
    api_url: str = "https://api.enablebanking.com"


class CollectorConfig(BaseModel):
    """Section `[collectors]` des réglages (sans secret)."""

    api_url: str = "http://api:8710"
    home: Path = Path("/var/lib/hub-collector")
    headless: bool = True
    bcf_overlap_days: int = Field(default=10, ge=1, le=90)
    viac_overlap_days: int = Field(default=14, ge=0, le=90)
    viac_report_every_days: int = Field(default=6, ge=1)
    diag_keep_days: int = Field(default=7, ge=1)
    check_poll_seconds: int = Field(default=60, ge=10)
    schedules: dict[str, str] = {
        "bcf": "30 7 * * 1-5",  # jours ouvrés 07:30 (une seule validation du push)
        "viac": "0 9 * * 0",  # dimanche 09:00
        "revolut": "15 7,13,19 * * *",  # trois synchros, la quatrième reste pour la main
    }
    urls: dict[str, str] = {}  # « bcf.url » : remplace une adresse de `[site]` (faux site)
    revolut: RevolutConfig = RevolutConfig()

    @property
    def profiles(self) -> Path:
        return self.home / "profiles"

    @property
    def diag(self) -> Path:
        return self.home / "diag"

    @property
    def state_dir(self) -> Path:
        return self.home / "state"


def config(settings: Settings) -> CollectorConfig:
    return CollectorConfig.model_validate(settings.domain("collectors"))


def credentials(settings: Settings, name: str) -> dict[str, Any]:
    """Section `collector-<nom>` du fichier de secrets monté dans ce conteneur seulement."""
    return secrets.section(
        settings.secrets.file, settings.secrets.age_key_file, f"collector-{name}"
    )


class Memory:
    """Mémoire d'un collecteur (empreintes déjà vues, dates, session) : un fichier JSON dans son
    volume, réécrit de façon atomique. Jamais de contenu bancaire."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.data: dict[str, Any] = json.loads(path.read_text()) if path.exists() else {}

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def put(self, key: str, value: Any) -> None:
        self.data[key] = value

    def seen(self) -> set[str]:
        return set(self.data.get("seen", []))

    def remember(self, digest: str) -> None:
        seen = list(self.data.get("seen", []))
        if digest not in seen:
            seen.append(digest)
        self.data["seen"] = seen[-5000:]

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=1, sort_keys=True))
        os.chmod(tmp, 0o600)
        tmp.replace(self.path)
