"""Planificateur minimal : crontab à cinq champs, exécutée dans le conteneur `scheduler`.

Même fichier sur le Mac et sur le Pi ; aucune dépendance à launchd ni à systemd. On n'a pas
repris supercronic pour ne pas embarquer un binaire de plus dans l'image.
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

from hub.core.clock import local_tz
from hub.core.logging import get_logger

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


def _run(command: tuple[str, ...]) -> int:
    return subprocess.run(command, check=False).returncode  # noqa: S603 - crontab du dépôt


def tick(jobs: list[Job], at: datetime, runner: Runner = _run) -> list[tuple[str, int]]:
    results: list[tuple[str, int]] = []
    for job in jobs:
        if job.due(at):
            code = runner(job.command)
            log.info("scheduler.job", command=job.command[0:3], exit_code=code)
            results.append((job.line, code))
    return results


def run_forever(crontab: Path, tz: str | None = None) -> None:  # pragma: no cover - boucle
    jobs = parse(crontab.read_text())
    zone = ZoneInfo(tz) if tz else local_tz()
    log.info("scheduler.start", jobs=len(jobs))
    while True:
        now = datetime.now(zone)
        nxt = (now + timedelta(minutes=1)).replace(second=0, microsecond=0)
        time.sleep(max(timedelta(0), nxt - now).total_seconds())
        tick(jobs, nxt)
