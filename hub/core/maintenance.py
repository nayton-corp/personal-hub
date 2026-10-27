"""Tâches de fond : nuit, vérification, sauvegarde. Appelées par la CLI et le planificateur."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import Engine

from hub.core import passkeys, proposals, ratelimit, sessions
from hub.core.context import HubContext
from hub.core.db import backup, integrity_check
from hub.core.logging import get_logger

log = get_logger("hub.maintenance")


def databases(hub: HubContext) -> dict[str, tuple[Engine, Path]]:
    out: dict[str, tuple[Engine, Path]] = {"core": (hub.core.engine, hub.core.path)}
    for d in hub.registry:
        out[d.name] = (d.engine(), hub.settings.db_path(d.name))
    return out


def nightly(hub: HubContext) -> dict[str, Any]:
    with hub.core.engine.begin() as conn:
        expired = proposals.expire(conn)
        purged = (
            sessions.purge_expired(conn) + passkeys.purge_challenges(conn) + ratelimit.purge(conn)
        )
    report = proposals.reconcile(hub)
    for d in hub.registry:
        d.nightly()
    result = {
        "expired": expired,
        "purged": purged,
        "reconciled_applied": report.marked_applied,
        "reconciled_released": report.released,
        "domains": hub.registry.names(),
    }
    log.info("nightly.done", **result)
    return result


@dataclass
class VerifyReport:
    ok: bool
    checks: dict[str, str] = field(default_factory=dict)


def verify(hub: HubContext) -> VerifyReport:
    """Intégrité SQLite de chaque base, puis santé de chaque domaine (le lot 1 y ajoute
    `verify-ledger`)."""
    report = VerifyReport(ok=True)
    for name, (_engine, path) in databases(hub).items():
        if not path.exists():
            report.checks[name] = "missing"
            report.ok = False
            continue
        result = integrity_check(path)
        report.checks[name] = result
        report.ok &= result == "ok"
    if not hub.core.is_current():
        report.checks["core.schema"] = "not at head"
        report.ok = False
    for d in hub.registry:
        health = d.health()
        report.checks[f"{d.name}.health"] = "ok" if health.ok else "failed"
        report.ok &= health.ok
    return report


def backup_all(hub: HubContext, dest: Path, stamp: str | None = None) -> list[Path]:
    """Copie `.backup` de chaque base, puis `integrity_check` sur chaque copie."""
    stamp = stamp or date.today().isoformat()  # noqa: DTZ011 - nom de fichier, jour local
    written: list[Path] = []
    for name, (engine, path) in databases(hub).items():
        if not path.exists():
            continue
        target = dest / f"{name}-{stamp}.db"
        backup(engine, target)
        check = integrity_check(target)
        if check != "ok":
            raise RuntimeError(f"copie corrompue : {target.name} ({check})")
        written.append(target)
    log.info("backup.done", files=len(written))
    return written
