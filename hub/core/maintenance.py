"""Tâches de fond : nuit, vérification, sauvegarde. Appelées par la CLI et le planificateur."""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import Engine

from hub.core import passkeys, proposals, ratelimit, secrets, sessions
from hub.core.clock import utcnow
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
    """Intégrité SQLite de chaque base, puis contrôle profond de chaque domaine (verify-ledger
    pour Finance)."""
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
        health = d.verify()
        report.checks[f"{d.name}.verify"] = "ok" if health.ok else "failed"
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


def prune_local_copies(dest: Path, keep_days: int) -> int:
    """Les copies locales servent au retour arrière immédiat ; restic garde l'historique."""
    cutoff = (utcnow() - timedelta(days=keep_days)).timestamp()
    removed = 0
    for f in dest.glob("*-????-??-??.db"):
        if f.stat().st_mtime < cutoff:
            f.unlink()
            removed += 1
    return removed


RESTIC_RETENTION = ("--keep-daily", "14", "--keep-weekly", "8", "--keep-monthly", "12")


def restic_backup(
    hub: HubContext, run: Callable[..., subprocess.CompletedProcess[bytes]] = subprocess.run
) -> list[str]:
    """Sauvegarde chiffrée des copies, des archives et de la réplique vers chaque dépôt restic
    (disque externe, puis second emplacement), puis rétention 14/8/12."""
    conf = secrets.section(hub.settings.secrets.file, hub.settings.secrets.age_key_file, "restic")
    password = conf.get("password")
    if not password:
        log.warning("restic.skipped", reason="no_password")
        return []
    repos = [
        str(r) for r in (hub.settings.backup.restic_local, conf.get("repository_offsite")) if r
    ]
    paths = [
        str(p)
        for p in (
            hub.settings.paths.backup,
            hub.settings.paths.archive,
            hub.settings.backup.replica,
        )
        if p is not None and Path(p).exists()
    ]
    env = {**os.environ, "RESTIC_PASSWORD": str(password)}
    restic = shutil.which("restic") or "restic"
    done: list[str] = []
    for repo in repos:
        base = [restic, "--repo", repo]
        if run([*base, "cat", "config"], env=env, capture_output=True).returncode != 0:
            run([*base, "init"], env=env, check=True, capture_output=True)
        run([*base, "backup", "--host", "hub", *paths], env=env, check=True, capture_output=True)
        run(
            [*base, "forget", "--host", "hub", *RESTIC_RETENTION, "--prune"],
            env=env,
            check=True,
            capture_output=True,
        )
        done.append(repo)
    log.info("restic.done", repositories=len(done))
    return done


def restore(hub: HubContext, stamp: str, source: Path | None = None) -> list[str]:
    """Remet chaque base depuis `<nom>-<stamp>.db` (services arrêtés), puis réconcilie.

    La copie est d'abord vérifiée, puis posée par renommage atomique ; les fichiers -wal et
    -shm de l'ancienne base sont retirés pour ne pas être rejoués sur la nouvelle.
    """
    source = source or hub.settings.paths.backup
    restored: list[str] = []
    hub.dispose()
    for name, (_engine, path) in databases(hub).items():
        copy = source / f"{name}-{stamp}.db"
        if not copy.exists():
            continue
        if integrity_check(copy) != "ok":
            raise RuntimeError(f"copie corrompue : {copy.name}")
        tmp = path.with_suffix(".restore")
        shutil.copyfile(copy, tmp)
        for suffix in ("-wal", "-shm"):
            Path(f"{path}{suffix}").unlink(missing_ok=True)
        os.replace(tmp, path)
        restored.append(name)
    if not restored:
        raise FileNotFoundError(f"aucune copie « {stamp} » dans {source}")
    report = proposals.reconcile(hub)
    log.info("restore.done", databases=restored, reconciled=report.marked_applied)
    return restored
