"""Reprise d'avant G4 (chantier « hub générique ») : les fichiers de secrets des anciens
conteneurs collecteurs (`<nom>.enc.yaml`, section `collector-<nom>`) deviennent les connexions
de la finance. Déclarée au cœur par le point d'entrée `hub.connection_imports` : `hub
connections import` l'appelle à chaque déploiement, sans effet une fois faite.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import Connection as Db

from hub.core import connections, connectors
from hub.core.errors import Problem
from hub.platform import secrets

# collecteur d'avant G4 → connecteur, nom affiché
LEGACY = {
    "bcf": ("bcf", "BCF"),
    "viac": ("viac", "VIAC"),
    "revolut": ("enable_banking", "Revolut"),
    "ibkr": ("ibkr", "IBKR"),
    "market": ("market", "Cours et cryptos"),
    "binance": ("binance", "Binance"),
    "kucoin": ("kucoin", "KuCoin"),
    "coinbase": ("coinbase", "Coinbase"),
}
# section de `[collectors]` d'avant G4 dont une connexion reprend les réglages
LEGACY_SECTIONS = {"enable_banking": "revolut", "market": "market"}


@dataclass
class ImportReport:
    imported: list[str]  # secrets repris
    kept: list[str]  # secrets déjà en base : rien n'est remplacé
    incomplete: list[str]  # fichier sans les champs exigés
    created: list[str]  # connexions créées

    def public(self) -> dict[str, list[str]]:
        return dict(self.__dict__)


def import_legacy(
    conn: Db,
    folder: Path,
    key_file: Path,
    by: str,
    collectors_settings: dict[str, Any],
) -> dict[str, list[str]]:
    """Reprend `<nom>.enc.yaml` (section `collector-<nom>`) dans les connexions, une fois :
    une connexion qui a déjà ses secrets les garde. Les réglages et horaires d'avant G4
    (`[collectors]`) passent dans la connexion s'ils n'y sont pas encore."""
    recipient = secrets.recipient(key_file)
    report = ImportReport([], [], [], [])
    raw_schedules = collectors_settings.get("schedules")
    schedules = raw_schedules if isinstance(raw_schedules, dict) else {}
    for name, (connector, label) in LEGACY.items():
        file = folder / f"{name}.enc.yaml"
        if not file.exists():
            continue
        values = {
            k: v
            for k, v in secrets.section(file, key_file, f"collector-{name}").items()
            if k != "token"
        }
        legacy = _legacy_settings(connector, collectors_settings)
        schedule = schedules.get(name)
        current = connections.get(conn, name)
        if current is None:
            current = connections.create(
                conn, name, connector, by, label=label, schedule=schedule, settings=legacy
            )
            report.created.append(name)
        elif (legacy and not current.settings) or (schedule and current.schedule is None):
            current = connections.update(
                conn,
                name,
                by,
                settings=legacy if legacy and not current.settings else None,
                schedule=schedule if current.schedule is None else None,
            )
        if current.secrets is not None:
            report.kept.append(name)
            _move_wallets(conn, current, key_file, recipient, by)
            continue
        try:
            connections.set_secrets(conn, name, values, recipient, by)
        except Problem:
            report.incomplete.append(name)
            continue
        report.imported.append(name)
        _move_wallets(conn, connections.require(conn, name), key_file, recipient, by)
    return report.public()


def _move_wallets(
    conn: Db, current: connections.Connection, key_file: Path, recipient: str, by: str
) -> None:
    """G5 : les portefeuilles passent des secrets aux réglages, où l'app les montre et les
    modifie (des adresses publiques et des clés publiques, pas des secrets d'accès)."""
    if current.connector != "market" or current.secrets is None or "wallets" in current.settings:
        return
    values = json.loads(secrets.decrypt_with(key_file, current.secrets))
    wallets = values.pop("wallets", None) if isinstance(values, dict) else None
    if not wallets:
        return
    try:
        connections.update(conn, current.id, by, settings={**current.settings, "wallets": wallets})
    except Problem:  # un portefeuille que l'app refuserait : il reste dans les secrets
        return
    if values:
        connections.set_secrets(conn, current.id, values, recipient, by)
    else:
        connections.clear_secrets(conn, current.id, by)


def _legacy_settings(connector: str, raw: dict[str, Any]) -> dict[str, Any]:
    spec = connectors.get(connector)
    section = raw.get(LEGACY_SECTIONS.get(connector, ""))
    out = (
        {k: v for k, v in section.items() if k in spec.settings}
        if spec is not None and isinstance(section, dict)
        else {}
    )
    if connector == "enable_banking":  # la banque était implicite : Revolut, Lituanie
        out = {"aspsp_name": "Revolut", "aspsp_country": "LT", **out}
    return out
