"""Tâches de fond : nuit, vérification, sauvegarde. Appelées par la CLI et le planificateur."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import Engine

from hub.core import (
    collectors,
    links,
    passkeys,
    proposal_events,
    proposal_reconcile,
    proposals,
    ratelimit,
    sessions,
    tokens,
)
from hub.core.context import HubContext
from hub.core.health import RESTIC_MARK, VERIFY_STATE
from hub.core.manifest import unguarded
from hub.core.notify import Message
from hub.kernel.clock import now_iso, utcnow
from hub.platform import secrets
from hub.platform.db import backup, integrity_check
from hub.platform.logging import get_logger

log = get_logger("hub.maintenance")


def databases(hub: HubContext) -> dict[str, tuple[Engine, Path]]:
    out: dict[str, tuple[Engine, Path]] = {"core": (hub.core.engine, hub.core.path)}
    for d in hub.registry:
        out[d.name] = (d.engine(), hub.settings.db_path(d.name))
    return out


def warn_token(hub: HubContext, token: tokens.TokenInfo) -> bool:
    """Alerte ntfy avant la fin d'un jeton : son nom et la commande qui le renouvelle."""
    end = token.expires_at[:10]
    if token.name.startswith("collector-"):  # jeton d'un service : make deploy en recrée un
        how = f"supprimer secrets/{token.name}.enc.yaml puis make deploy"
    else:
        how = f"hub token rotate {token.id}"
    title = f"Jeton « {token.name} » : {'fini' if token.expired else 'fin'} le {end}"
    return hub.notifier.send(Message(title[:120], how, tags="key"))


def nightly(hub: HubContext) -> dict[str, Any]:
    with hub.core.engine.begin() as conn:
        expired = proposals.expire(conn)
        purged = (
            sessions.purge_expired(conn)
            + passkeys.purge_challenges(conn)
            + ratelimit.purge(conn)
            + collectors.purge_links(conn)
        )
        ending = tokens.expiring(conn)
    warned = sum(warn_token(hub, t) for t in ending)
    report = proposal_reconcile.reconcile(hub)
    for d in hub.registry:
        d.nightly()
    synced = proposal_events.sync_events(hub)
    result = {
        "expired": expired,
        "requested": synced["requested"],
        "obsoleted": synced["obsoleted"],
        "notified": synced["notified"],
        "purged": purged,
        "tokens_warned": warned,
        "reconciled_applied": report.marked_applied,
        "reconciled_released": report.released,
        "domains": hub.registry.names(),
    }
    log.info("nightly.done", **result)
    return result


@dataclass
class VerifyReport:
    """`ok` : l'intégrité (bases, chaînes d'empreintes, schémas, triggers), qui seule bloque une
    mise à jour. `warnings` : ce que les domaines signalent sans mettre l'intégrité en cause
    (un écart entre deux calculs) ; ça alerte, ça ne bloque pas (audit du 10/11, V1)."""

    ok: bool
    checks: dict[str, str] = field(default_factory=dict)
    warnings: dict[str, list[str]] = field(default_factory=dict)

    def public(self) -> dict[str, Any]:
        return {"ok": self.ok, "checks": self.checks, "warnings": self.warnings}

    @property
    def failed(self) -> list[str]:
        return sorted(k for k, v in self.checks.items() if v != "ok")


def verify(hub: HubContext) -> VerifyReport:
    """Intégrité SQLite de chaque base, puis contrôle profond de chaque domaine (verify-ledger
    pour Finance) et triggers d'ajout seul de ses tables protégées (manifeste)."""
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
    elif hub.core.path.exists():
        with hub.core.engine.connect() as conn:
            ledger = links.LEDGER.verify(conn)
        report.checks["core.ledger"] = "ok" if ledger.ok else "failed"
        report.ok &= ledger.ok
    for d in hub.registry:
        health = d.verify()
        report.checks[f"{d.name}.verify"] = "ok" if health.ok else "failed"
        report.ok &= health.ok
        if health.warnings:
            report.warnings[d.name] = sorted(health.warnings)
        protected = d.manifest().protected_tables
        if protected and health.db != "missing":
            with d.engine().connect() as conn:
                open_tables = unguarded(conn, protected)
            report.checks[f"{d.name}.protected"] = (
                "ok" if not open_tables else f"sans trigger : {', '.join(open_tables)}"
            )
            report.ok &= not open_tables
    try:  # le contrôle de santé y lit les avertissements et l'âge du dernier contrôle
        state = hub.settings.paths.data / VERIFY_STATE
        state.write_text(json.dumps({"at": now_iso(), **report.public()}))
    except OSError as exc:
        log.warning("verify.state_unwritable", error=type(exc).__name__)
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


KEEP_PREDEPLOY = 3  # versions dont on garde la copie d'avant migration (retour arrière)


def prune_local_copies(dest: Path, keep_days: int) -> int:
    """Les copies locales servent au retour arrière immédiat ; restic garde l'historique. Les
    copies d'avant déploiement (`<base>-predeploy-<tag>.db`) n'ont pas de date dans leur nom :
    on garde celles des `KEEP_PREDEPLOY` dernières versions (audit du 10/11, D1)."""
    cutoff = (utcnow() - timedelta(days=keep_days)).timestamp()
    removed = 0
    for f in dest.glob("*-????-??-??.db"):
        if f.stat().st_mtime < cutoff:
            f.unlink()
            removed += 1
    by_tag: dict[str, list[Path]] = {}
    for f in dest.glob("*-predeploy-*.db"):
        by_tag.setdefault(f.stem.split("-predeploy-", 1)[1], []).append(f)
    newest_first = sorted(
        by_tag, key=lambda tag: max(f.stat().st_mtime for f in by_tag[tag]), reverse=True
    )
    for tag in newest_first[KEEP_PREDEPLOY:]:
        for f in by_tag[tag]:
            f.unlink()
            removed += 1
    return removed


RESTIC_RETENTION = ("--keep-daily", "14", "--keep-weekly", "8", "--keep-monthly", "12")
Run = Callable[..., "subprocess.CompletedProcess[bytes]"]


@dataclass(frozen=True)
class Restic:
    """Ce qu'il faut pour parler à restic : dépôts (local, puis hors de la machine) et
    environnement. Section `restic` de `secrets.enc.yaml` : `password`, `repository_offsite`
    (adresse du second dépôt) et `env` (identifiants de son stockage, ex. AWS_ACCESS_KEY_ID)."""

    repos: tuple[str, ...]
    env: dict[str, str]
    offsite: bool

    @classmethod
    def load(cls, hub: HubContext) -> Restic | None:
        s = hub.settings
        conf = secrets.section(s.secrets.file, s.secrets.age_key_file, "restic")
        password = conf.get("password")
        if not password:
            return None
        offsite = conf.get("repository_offsite")
        raw = conf.get("env")
        extra: dict[Any, Any] = raw if isinstance(raw, dict) else {}
        env = {
            **os.environ,
            # racine en lecture seule dans le conteneur : le cache va dans /tmp
            "RESTIC_CACHE_DIR": os.environ.get("RESTIC_CACHE_DIR", "/tmp/restic-cache"),  # noqa: S108
            **{str(k): str(v) for k, v in extra.items()},
            "RESTIC_PASSWORD": str(password),
        }
        repos = tuple(str(r) for r in (s.backup.restic_local, offsite) if r)
        return cls(repos, env, bool(offsite))

    def base(self, repo: str) -> list[str]:
        return [shutil.which("restic") or "restic", "--repo", repo]


def _readable(path: Path) -> list[str]:
    """Les fichiers lisibles sous `path` : un fichier de configuration que le conteneur ne peut
    pas lire (droits 0600 d'un autre utilisateur) est laissé, pas une raison d'échouer."""
    files = [path] if path.is_file() else sorted(p for p in path.rglob("*") if p.is_file())
    kept = [str(f) for f in files if os.access(f, os.R_OK)]
    if len(kept) < len(files):
        log.warning("restic.unreadable", skipped=len(files) - len(kept))
    return kept


def backup_paths(hub: HubContext) -> list[str]:
    """Ce que restic emporte : les copies des bases, l'archive chiffrée, la réplique, et la
    configuration sans laquelle rien ne se relance (secrets chiffrés par age, `deploy/.env`,
    secrets des collecteurs : audit du 10/11, K1). La clé age, elle, reste dans le kit de
    secours : c'est elle qui ouvre le tout."""
    s = hub.settings
    data = [p for p in (s.paths.backup, s.paths.archive, s.backup.replica) if p is not None]
    config = [f for p in (s.secrets.file, *s.backup.extra) if p.exists() for f in _readable(p)]
    return list(dict.fromkeys([*(str(p) for p in data if p.exists()), *config]))


def restic_backup(hub: HubContext, run: Run = subprocess.run) -> list[str]:
    """Sauvegarde chiffrée vers chaque dépôt restic (local, puis hors de la machine), puis
    rétention 14/8/12. Un dépôt en échec n'empêche pas l'autre ; la commande échoue à la fin,
    et le planificateur alerte."""
    restic = Restic.load(hub)
    if restic is None:
        log.warning("restic.skipped", reason="no_password")
        return []
    paths = backup_paths(hub)
    done: list[str] = []
    for repo in restic.repos:
        base, env = restic.base(repo), restic.env
        try:
            if run([*base, "cat", "config"], env=env, capture_output=True).returncode != 0:
                run([*base, "init"], env=env, check=True, capture_output=True)
            run(
                [*base, "backup", "--host", "hub", *paths], env=env, check=True, capture_output=True
            )
            run(
                [*base, "forget", "--host", "hub", *RESTIC_RETENTION, "--prune"],
                env=env,
                check=True,
                capture_output=True,
            )
        except (subprocess.CalledProcessError, OSError) as exc:
            log.error("restic.failed", repository=len(done) + 1, error=type(exc).__name__)
            continue
        done.append(repo)
    if len(done) < len(restic.repos):
        raise RuntimeError(f"restic : {len(restic.repos) - len(done)} dépôt(s) en échec")
    _mark(hub, RESTIC_MARK, {"repositories": len(done), "offsite": restic.offsite})
    log.info("restic.done", repositories=len(done), offsite=restic.offsite)
    return done


def _mark(hub: HubContext, name: str, payload: dict[str, Any]) -> None:
    """Trace d'un passage réussi, lue par le contrôle de santé (`hub ops health`)."""
    try:
        (hub.settings.paths.backup / name).write_text(json.dumps({"at": now_iso(), **payload}))
    except OSError as exc:
        log.warning("restic.mark_unwritable", error=type(exc).__name__)


def restic_check(hub: HubContext, run: Run = subprocess.run) -> dict[str, int]:
    """Essai de restauration, chaque semaine (audit du 10/11, K1) : pour chaque dépôt,
    `restic check` (structure et un échantillon des données), puis les copies de bases les plus
    récentes sont ressorties du dépôt, comparées à l'original et passées à `integrity_check`.
    Une sauvegarde qu'on n'a jamais relue n'en est pas une."""
    restic = Restic.load(hub)
    if restic is None:
        raise RuntimeError("restic : pas de mot de passe, rien à contrôler")
    dest = hub.settings.paths.backup
    stamps = sorted(f.stem.removeprefix("core-") for f in dest.glob("core-????-??-??.db"))
    if not stamps:
        raise RuntimeError("aucune copie locale à comparer : lancer `hub backup --restic`")
    copies = sorted(f.resolve() for f in dest.glob(f"*-{stamps[-1]}.db"))
    scratch = Path(tempfile.mkdtemp(prefix=".restore-test-", dir=dest))
    try:
        for repo in restic.repos:
            base, env = restic.base(repo), restic.env
            run(
                [*base, "check", "--read-data-subset", "5%"],
                env=env,
                check=True,
                capture_output=True,
            )
            target = scratch / str(restic.repos.index(repo))
            wanted = [arg for copy in copies for arg in ("--include", str(copy))]
            run(
                [*base, "restore", "latest", "--host", "hub", "--target", str(target), *wanted],
                env=env,
                check=True,
                capture_output=True,
            )
            for copy in copies:
                out = target / str(copy).lstrip("/")
                if not out.exists() or _digest(out) != _digest(copy):
                    raise RuntimeError(f"copie restaurée différente de l'original : {copy.name}")
                if integrity_check(out) != "ok":
                    raise RuntimeError(f"copie restaurée corrompue : {copy.name}")
            shutil.rmtree(target, ignore_errors=True)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    result = {"repositories": len(restic.repos), "databases": len(copies)}
    _mark(hub, "restic.check.json", result)
    log.info("restic.checked", **result)
    return result


def _digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


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
    report = proposal_reconcile.reconcile(hub)
    log.info("restore.done", databases=restored, reconciled=report.marked_applied)
    return restored
