"""Planificateur minimal : crontab à cinq champs, exécutée dans le conteneur `scheduler`.

Même fichier sur le Mac et sur le Pi ; aucune dépendance à launchd ni à systemd. On n'a pas
repris supercronic pour ne pas embarquer un binaire de plus dans l'image. Les jobs d'un même
tour se suivent. La dernière minute servie est notée dans un fichier d'état : au redémarrage,
chaque job manqué pendant l'arrêt (au plus un jour en arrière) est rejoué une fois (audit m18).

Chaque minute, il lance aussi ce que l'app a demandé (`requested`, core.tasks), avec la même
commande que la nuit.

Un job qui sort en erreur est signalé à `on_failure` (une alerte ntfy, posée par la CLI) : une
nuit ratée ne reste plus dans les journaux du conteneur (audit du 10/11, O1). Le code de sortie
`REPORTED` dit que la commande a déjà prévenu elle-même, avec ses détails.
"""

from __future__ import annotations

import shlex
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from hub.kernel.clock import local_tz
from hub.platform.logging import get_logger

log = get_logger("hub.scheduler")

_RANGES = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 7))  # minute, heure, jour, mois, jour de semaine


def _field(spec: str, low: int, high: int) -> frozenset[int]:
    values: set[int] = set()
    for part in spec.split(","):
        step = 1
        if "/" in part:
            part, step_s = part.split("/", 1)
            step = int(step_s)
            if step < 1:
                raise ValueError("pas invalide")
        if part == "*":
            start, end = low, high
        elif "-" in part:
            a, b = part.split("-", 1)
            start, end = int(a), int(b)
        else:
            start = end = int(part)
        if start < low or end > high or start > end:
            raise ValueError(f"valeur hors limites : {part}")
        values.update(range(start, end + 1, step))
    return frozenset(values)


@dataclass(frozen=True)
class Job:
    minutes: frozenset[int]
    hours: frozenset[int]
    days: frozenset[int]
    months: frozenset[int]
    weekdays: frozenset[int]
    command: tuple[str, ...]
    line: str

    def due(self, at: datetime) -> bool:
        weekday = (at.weekday() + 1) % 7  # cron : 0 = dimanche
        return (
            at.minute in self.minutes
            and at.hour in self.hours
            and at.day in self.days
            and at.month in self.months
            and weekday in self.weekdays
        )


def parse(text: str) -> list[Job]:
    jobs: list[Job] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 5)
        if len(parts) < 6:
            raise ValueError(f"ligne de crontab incomplète : {line}")
        fields = [_field(p, lo, hi) for p, (lo, hi) in zip(parts[:5], _RANGES, strict=True)]
        weekdays = frozenset(0 if d == 7 else d for d in fields[4])  # 7 = dimanche aussi
        jobs.append(
            Job(
                fields[0],
                fields[1],
                fields[2],
                fields[3],
                weekdays,
                tuple(shlex.split(parts[5])),
                line,
            )
        )
    return jobs


Runner = Callable[[tuple[str, ...]], int]
OnFailure = Callable[[tuple[str, ...], int], None]
CATCH_UP = timedelta(days=1)  # un arrêt plus long ne rejoue pas plus loin
REPORTED = 3  # échec que la commande a déjà signalé elle-même (`hub verify --notify`)
NOT_FOUND = 127  # commande introuvable, comme le shell


def missed(jobs: list[Job], since: datetime, until: datetime) -> list[Job]:
    """Les jobs dus entre `since` (exclue) et `until` (exclue), chacun une fois, dans l'ordre de
    la crontab ; au plus `CATCH_UP` en arrière."""
    start = max(since, until - CATCH_UP).replace(second=0, microsecond=0)
    found: list[Job] = []
    at = start + timedelta(minutes=1)
    while at < until:
        found += [j for j in jobs if j not in found and j.due(at)]
        at += timedelta(minutes=1)
    return found


def _run(command: tuple[str, ...]) -> int:
    try:
        return subprocess.run(command, check=False).returncode  # noqa: S603 - crontab du dépôt
    except OSError:
        return NOT_FOUND


def serve(job: Job, event: str, runner: Runner = _run, on_failure: OnFailure | None = None) -> int:
    """Lance un job, journalise son code de sortie et signale un échec."""
    code = runner(job.command)
    log.info(event, command=job.command[0:3], exit_code=code)
    if code not in (0, REPORTED) and on_failure is not None:
        try:
            on_failure(job.command, code)
        except Exception as exc:  # une alerte perdue n'arrête pas le planificateur
            log.warning("scheduler.alert_failed", error=type(exc).__name__)
    return code


def tick(
    jobs: list[Job], at: datetime, runner: Runner = _run, on_failure: OnFailure | None = None
) -> list[tuple[str, int]]:
    return [
        (job.line, serve(job, "scheduler.job", runner, on_failure)) for job in jobs if job.due(at)
    ]


Requested = Callable[[], list[tuple[str, ...]]]


def serve_requested(
    requested: Requested, runner: Runner = _run, on_failure: OnFailure | None = None
) -> list[tuple[tuple[str, ...], int]]:
    """Les commandes demandées depuis l'app (core.tasks), lancées comme un job de la crontab.
    Une demande illisible (base occupée) attend la minute suivante."""
    try:
        commands = requested()
    except Exception as exc:
        log.warning("scheduler.requests_unreadable", error=type(exc).__name__)
        return []
    out = []
    for command in commands:
        job = Job(frozenset(), frozenset(), frozenset(), frozenset(), frozenset(), command, "")
        out.append((command, serve(job, "scheduler.requested", runner, on_failure)))
    return out


def _last_served(state: Path | None) -> datetime | None:
    try:
        return datetime.fromisoformat(state.read_text().strip()) if state else None
    except (OSError, ValueError):
        return None


def run_forever(
    crontab: Path,
    tz: str | None = None,
    state: Path | None = None,
    on_failure: OnFailure | None = None,
    requested: Requested | None = None,
) -> None:  # pragma: no cover - boucle
    """`state` : fichier de la dernière minute servie (rattrapage au redémarrage) ;
    `requested` : les commandes demandées depuis l'app, lues chaque minute."""
    jobs = parse(crontab.read_text())
    zone = ZoneInfo(tz) if tz else local_tz()
    last = _last_served(state)
    log.info("scheduler.start", jobs=len(jobs), last_served=last.isoformat() if last else None)
    while True:
        now = datetime.now(zone)
        nxt = (now + timedelta(minutes=1)).replace(second=0, microsecond=0)
        time.sleep(max(timedelta(0), nxt - now).total_seconds())
        if last is not None:
            for job in missed(jobs, last, nxt):
                serve(job, "scheduler.catch_up", on_failure=on_failure)
        tick(jobs, nxt, on_failure=on_failure)
        if requested is not None:
            serve_requested(requested, on_failure=on_failure)
        last = nxt
        if state is not None:
            try:
                state.write_text(nxt.isoformat())
            except OSError as exc:
                log.warning("scheduler.state_unwritable", error=type(exc).__name__)
