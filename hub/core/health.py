"""Contrôle de santé de l'instance (`hub ops health`, chaque heure dans le planificateur).

Ce que personne ne regardait (audit du 10/11, O1 et D1) : un disque qui se remplit, une réplique
Litestream arrêtée, une sauvegarde qui n'a plus tourné, un import resté en plan. Chaque écart
donne une alerte ntfy à son apparition, un rappel par jour tant qu'il dure, et un mot quand il
est réglé. Quand tout va bien, un signal de vie part vers l'adresse `monitoring.heartbeat_url`
de `secrets.enc.yaml` (si elle existe) : c'est son absence qui dit que le hub est éteint.

Des textes génériques : un nom de volume, un pourcentage, un âge en heures. Jamais un montant.
"""

from __future__ import annotations

import json
import os
import shutil
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from hub.core.context import HubContext
from hub.core.notify import Message
from hub.kernel.clock import iso, parse_iso, utcnow
from hub.platform import secrets
from hub.platform.logging import get_logger

log = get_logger("hub.health")

STATE = "health.json"  # dans paths.data : alertes en cours, pour ne pas répéter chaque heure
RESTIC_MARK = "restic.last.json"  # dans paths.backup : dernier passage restic réussi
VERIFY_STATE = "verify.json"  # dans paths.data : dernier `hub verify`
WEEK_HOURS = 168


@dataclass(frozen=True)
class Finding:
    key: str  # stable d'un passage à l'autre : « disk:data », « replica:finance »
    title: str
    detail: str
    remind_hours: int | None = None  # rappel propre à ce constat ; sinon celui des réglages


def _percent(path: Path) -> int:
    usage = shutil.disk_usage(path)
    return round(usage.used * 100 / usage.total) if usage.total else 0


def disks(hub: HubContext) -> list[Finding]:
    """Un volume par système de fichiers distinct, au-delà du seuil de remplissage."""
    s = hub.settings
    seen: set[int] = set()
    found = []
    volumes = {
        "données": s.paths.data,
        "sauvegardes": s.paths.backup,
        "archives": s.paths.archive,
        "réplique": s.backup.replica,
        "dépôt restic": s.backup.restic_local,
    }
    for name, path in volumes.items():
        if path is None or not path.exists():
            continue
        device = os.stat(path).st_dev
        if device in seen:
            continue
        seen.add(device)
        used = _percent(path)
        if used >= s.monitoring.disk_percent:
            found.append(
                Finding(
                    f"disk:{name}", "Disque presque plein", f"Volume {name} : {used} % utilisés."
                )
            )
    return found


NS = 1_000_000_000  # les dates de fichier se comparent en nanosecondes entières


def _newest(root: Path) -> int:
    newest = 0
    for folder, _dirs, files in os.walk(root):
        for f in files:
            try:
                newest = max(newest, os.stat(os.path.join(folder, f)).st_mtime_ns)
            except OSError:  # segment retiré par Litestream pendant la marche
                continue
    return newest


def replicas(hub: HubContext, databases: dict[str, Path]) -> list[Finding]:
    """La réplique Litestream de chaque base suit ses écritures, au retard toléré près."""
    root = hub.settings.backup.replica
    if root is None or not root.is_dir():
        return []  # pas de réplique sur cette instance (développement)
    limit = hub.settings.monitoring.replica_hours * 3600
    found = []
    for name, path in databases.items():
        if not path.exists():
            continue
        written = max(p.stat().st_mtime_ns for p in (path, Path(f"{path}-wal")) if p.exists())
        late = (written - _newest(root / f"{name}.db")) // NS
        if late > limit:
            found.append(
                Finding(
                    f"replica:{name}",
                    "Réplique en retard",
                    f"Base {name} : la réplique Litestream a plus de {late // 3600} h de "
                    "retard sur la base.",
                )
            )
    return found


def _hours(late: timedelta) -> int:
    return int(late.total_seconds() // 3600)


def _read(path: Path) -> dict[str, Any]:
    try:
        state = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return state if isinstance(state, dict) else {}


def backups(hub: HubContext, now: datetime, since: datetime) -> list[Finding]:
    """La copie de nuit et le passage restic datent de moins de `backup_hours`, et une copie
    part hors de la machine."""
    limit = timedelta(hours=hub.settings.monitoring.backup_hours)
    dest = hub.settings.paths.backup
    found = []

    def age(files: list[Path]) -> timedelta:
        """Depuis le plus récent de ces fichiers ; sans aucun, depuis le premier contrôle."""
        if not files:
            return now - since
        newest = max(f.stat().st_mtime_ns for f in files)
        return now - datetime.fromtimestamp(newest // NS, tz=now.tzinfo)

    late = age(list(dest.glob("core-????-??-??.db")) if dest.is_dir() else [])
    if late > limit:
        found.append(
            Finding(
                "backup",
                "Sauvegarde en retard",
                f"Dernière copie des bases : il y a {_hours(late)} h.",
            )
        )
    if hub.settings.backup.restic_local is None:
        return found
    mark = dest / RESTIC_MARK
    late = age([mark] if mark.exists() else [])
    if late > limit:
        found.append(
            Finding(
                "restic",
                "Sauvegarde chiffrée en retard",
                f"Dernier passage restic réussi : il y a {_hours(late)} h.",
            )
        )
    elif mark.exists() and _read(mark).get("offsite") is False:
        found.append(
            Finding(
                "offsite",
                "Pas de sauvegarde hors de la machine",
                "Les bases et leurs sauvegardes sont sur le même disque. Ajouter "
                "`repository_offsite` à la section restic des secrets (docs/exploitation).",
                remind_hours=WEEK_HOURS,
            )
        )
    return found


def verified(hub: HubContext, now: datetime, since: datetime) -> list[Finding]:
    """Le contrôle de nuit a tourné, et ce qu'il signale sans bloquer (un écart entre deux
    calculs) arrive jusqu'à toi."""
    state = _read(hub.settings.paths.data / VERIFY_STATE)
    at = parse_iso(state["at"]) if isinstance(state.get("at"), str) else since
    late = now - at
    found = []
    if late > timedelta(hours=hub.settings.monitoring.backup_hours):
        found.append(
            Finding(
                "verify:late",
                "Contrôle de nuit en retard",
                f"Dernier contrôle d'intégrité : il y a {_hours(late)} h.",
            )
        )
    warnings = state.get("warnings")
    for domain, codes in (warnings if isinstance(warnings, dict) else {}).items():
        found += [
            Finding(
                f"verify:{domain}:{code}",
                "Contrôle des chiffres : écart à regarder",
                f"Domaine {domain} : « {code} ». Rien n'est bloqué ; le détail est dans "
                "`hub verify`.",
            )
            for code in codes
        ]
    return found


EXPIRY_NOTICE = timedelta(days=14)


def expiries(hub: HubContext, now: datetime) -> list[Finding]:
    """Les échéances déclarées dans les réglages, deux semaines avant leur date."""
    found = []
    for name, day in hub.settings.monitoring.expiries.items():
        left = day - now.date()
        if left <= EXPIRY_NOTICE:
            when = f"dans {left.days} jours" if left.days > 0 else "atteinte"
            detail = f"{name[:80]} : échéance le {day.isoformat()} ({when})."
            if day == date.min:
                detail = f"{name[:80]} : date illisible dans HUB_EXPIRIES (attendu AAAA-MM-JJ)."
            found.append(
                Finding(f"expiry:{name}", "Échéance proche", detail, remind_hours=WEEK_HOURS)
            )
    return found


def domains(hub: HubContext) -> list[Finding]:
    """Les avertissements que chaque domaine remonte dans sa santé (codes génériques)."""
    found = []
    for d in hub.registry:
        try:
            warnings = d.health().warnings
        except Exception as exc:  # un domaine en faute ne cache pas les autres contrôles
            warnings = (f"health.{type(exc).__name__}",)
        found += [
            Finding(f"{d.name}:{w}", f"Domaine {d.name} : à regarder", f"Avertissement « {w} ».")
            for w in warnings
        ]
    return found


def collect(hub: HubContext, now: datetime, since: datetime) -> list[Finding]:
    from hub.core.maintenance import databases

    paths = {name: path for name, (_engine, path) in databases(hub).items()}
    return [
        *disks(hub),
        *replicas(hub, paths),
        *backups(hub, now, since),
        *verified(hub, now, since),
        *expiries(hub, now),
        *domains(hub),
    ]


def _get(url: str) -> None:  # pragma: no cover - réseau
    with urllib.request.urlopen(url, timeout=10):  # noqa: S310 - https vérifié par l'appelant
        pass


def heartbeat(hub: HubContext, get: Callable[[str], None] = _get) -> bool:
    """Signal de vie : une requête vers l'adresse secrète, sans rien dedans."""
    try:
        conf = secrets.section(
            hub.settings.secrets.file, hub.settings.secrets.age_key_file, "monitoring"
        )
    except secrets.SecretsError:
        return False
    url = conf.get("heartbeat_url")
    if not isinstance(url, str) or not url.startswith("https://"):
        return False
    try:
        get(url)
    except Exception as exc:  # le prochain passage réessaiera
        log.warning("health.heartbeat_failed", error=type(exc).__name__)
        return False
    return True


def run(
    hub: HubContext, now: datetime | None = None, get: Callable[[str], None] = _get
) -> dict[str, Any]:
    """Un passage : alerte ce qui apparaît, rappelle ce qui dure, dit ce qui est réglé."""
    now = now or utcnow()
    path = hub.settings.paths.data / STATE
    state = _read(path)
    since = parse_iso(state["since"]) if isinstance(state.get("since"), str) else now
    alerts: dict[str, dict[str, str]] = dict(state.get("alerts") or {})
    findings = collect(hub, now, since)
    sent = 0
    for f in findings:
        known = alerts.get(f.key)
        remind = timedelta(hours=f.remind_hours or hub.settings.monitoring.remind_hours)
        if known is not None and now - parse_iso(known["at"]) < remind:
            continue
        if hub.notifier.send(Message(f.title, f.detail, priority="high", tags="warning")):
            alerts[f.key] = {"at": iso(now), "title": f.title}
            sent += 1
    current = {f.key for f in findings}
    for key in [k for k in alerts if k not in current]:
        title = alerts.pop(key)["title"]
        hub.notifier.send(Message(f"Réglé : {title}", "Le contrôle de santé ne le voit plus."))
    try:
        path.write_text(json.dumps({"since": iso(since), "alerts": alerts}))
    except OSError as exc:
        log.warning("health.state_unwritable", error=type(exc).__name__)
    alive = not findings and heartbeat(hub, get)
    result = {"ok": not findings, "findings": sorted(current), "alerted": sent, "heartbeat": alive}
    log.info("health.done", **result)
    return result
