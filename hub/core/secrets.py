"""Secrets : `secrets.enc.yaml` chiffré par age, déchiffré en mémoire au démarrage.

La clé age de la machine arrive en secret Docker (`/run/secrets/age_key`) ; rien de déchiffré
n'est jamais écrit sur disque. Chaque processus ne reçoit que la section qui le concerne.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pyrage
import yaml


class SecretsError(RuntimeError):
    pass


def _identity(key_file: Path) -> Any:
    lines = [
        line.strip()
        for line in key_file.read_text().splitlines()
        if line.strip().startswith("AGE-SECRET-KEY-")
    ]
    if len(lines) != 1:
        raise SecretsError("la clé age doit contenir exactement une identité")
    return pyrage.x25519.Identity.from_str(lines[0])


def load(file: Path, key_file: Path) -> dict[str, Any]:
    if not file.exists():
        return {}
    if not key_file.exists():
        raise SecretsError("clé age absente : secrets illisibles")
    try:
        plain = pyrage.decrypt(file.read_bytes(), [_identity(key_file)])
    except Exception as exc:  # pyrage lève des types variés selon l'erreur
        raise SecretsError("déchiffrement impossible") from exc
    data = yaml.safe_load(plain.decode())
    if not isinstance(data, dict):
        raise SecretsError("secrets.enc.yaml doit contenir un dictionnaire")
    return data


def section(file: Path, key_file: Path, name: str) -> dict[str, Any]:
    value = load(file, key_file).get(name, {})
    if not isinstance(value, dict):
        raise SecretsError(f"section {name!r} invalide")
    return value


def encrypt_for(recipient: str, plain: bytes) -> bytes:
    """Utilisé par les tests et par `hub secrets encrypt` ; la clé publique suffit."""
    return bytes(pyrage.encrypt(plain, [pyrage.x25519.Recipient.from_str(recipient)]))
