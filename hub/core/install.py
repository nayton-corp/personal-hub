"""Première installation (chantier « hub générique », G6) : `hub init`.

Prépare une machine sans rien demander d'autre que Docker : la clé age (seul secret en clair),
les secrets chiffrés (mot de passe restic tiré au hasard), les dossiers montés et `deploy/.env`
écrit depuis `deploy/.env.example`. Rien de ce qui existe n'est remplacé : relancer `hub init`
ne fait que compléter ce qui manque.
"""

from __future__ import annotations

import os
import re
import secrets as random
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pyrage
import yaml

from hub.core.profile import ProfileError, clean_country
from hub.kernel.money import CurrencyError, exponent
from hub.platform import secrets

_LINE = re.compile(r"^([A-Z_]+)=(.*)$")
_ORIGIN = re.compile(r"^https://[A-Za-z0-9.-]+(:\d+)?$")


class InitError(ValueError):
    pass


@dataclass(frozen=True)
class Choices:
    config: Path  # clé age et secrets, hors de tout dossier synchronisé
    home: Path  # boîte d'entrée et sauvegardes locales
    origin: str = "https://hub.votre-tailnet.ts.net"
    timezone: str = "Europe/Zurich"
    currency: str = "CHF"
    country: str = "CH"

    def checked(self) -> Choices:
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            raise InitError(f"fuseau inconnu : {self.timezone!r} (ex. Europe/Paris)") from None
        currency = self.currency.strip().upper()
        try:
            exponent(currency)
        except CurrencyError as exc:
            raise InitError(str(exc)) from None
        try:
            country = clean_country(self.country)
        except ProfileError as exc:
            raise InitError(str(exc)) from None
        if not _ORIGIN.match(self.origin):
            raise InitError("origine : https://<nom>.<tailnet>.ts.net, sans chemin")
        if not (self.config.is_absolute() and self.home.is_absolute()):
            raise InitError("les dossiers doivent être des chemins absolus")
        return Choices(self.config, self.home, self.origin, self.timezone, currency, country)

    def env(self) -> dict[str, str]:
        return {
            "HUB_PUBLIC_ORIGIN": self.origin,
            "HUB_TZ": self.timezone,
            "HUB_CURRENCY": self.currency,
            "HUB_COUNTRY": self.country,
            "HUB_INBOX": str(self.home / "inbox"),
            "HUB_REPLICA": str(self.home / "backup" / "litestream"),
            "HUB_RESTIC_LOCAL": str(self.home / "backup" / "restic"),
            "HUB_AGE_KEY": str(self.config / "age.key"),
            "HUB_SECRETS": str(self.config / "secrets.enc.yaml"),
            "HUB_COLLECTOR_SECRETS": str(self.config / "collectors"),
        }


@dataclass
class Report:
    created: list[str] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)
    public_key: str = ""


def render_env(template: str, values: dict[str, str]) -> str:
    """Le modèle avec ses commentaires, chaque clé connue remplacée par sa valeur."""
    out = []
    for line in template.splitlines():
        m = _LINE.match(line)
        out.append(f"{m.group(1)}={values[m.group(1)]}" if m and m.group(1) in values else line)
    return "\n".join(out) + "\n"


def _write(path: Path, data: bytes, mode: int) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    os.chmod(path, mode)  # le umask a pu retirer des droits ; 0400 doit valoir 0400


def _folder(path: Path, mode: int, report: Report) -> None:
    if path.is_dir():
        report.kept.append(str(path))
        return
    path.mkdir(parents=True, mode=mode)
    report.created.append(str(path))


def age_key(path: Path, report: Report) -> str:
    """Crée la clé age de la machine si elle manque ; renvoie sa clé publique."""
    if path.exists():
        report.kept.append(str(path))
        return secrets.recipient(path)
    identity = pyrage.x25519.Identity.generate()
    public = str(identity.to_public())
    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    body = f"# created: {stamp}\n# public key: {public}\n{identity}\n"
    _write(path, body.encode(), 0o400)
    report.created.append(str(path))
    return public


def secrets_file(path: Path, recipient: str, report: Report) -> None:
    """Secrets chiffrés de l'instance : un mot de passe restic tiré au hasard, jamais affiché."""
    if path.exists():
        report.kept.append(str(path))
        return
    plain = yaml.safe_dump({"restic": {"password": random.token_urlsafe(32)}}).encode()
    _write(path, secrets.encrypt_for(recipient, plain), 0o600)
    report.created.append(str(path))


def run(choices: Choices, env_file: Path, template: Path) -> Report:
    c = choices.checked()
    report = Report()
    _folder(c.config, 0o700, report)
    report.public_key = age_key(c.config / "age.key", report)
    secrets_file(c.config / "secrets.enc.yaml", report.public_key, report)
    _folder(c.config / "collectors", 0o700, report)
    for sub in ("inbox", "backup/litestream", "backup/restic"):
        _folder(c.home / sub, 0o700, report)
    if env_file.exists():
        report.kept.append(str(env_file))
    else:
        _write(env_file, render_env(template.read_text(), c.env()).encode(), 0o600)
        report.created.append(str(env_file))
    return report
