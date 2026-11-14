"""Tâches planifiées relancées à la main (Réglages › État des sources, État du hub).

Une tâche, c'est ce que la crontab lance seule (`deploy/crontab`) ou un morceau de la tâche de
nuit d'un domaine (`NightlyTasks`). Chacune garde dans `task_runs` son dernier passage, qu'elle
vienne de la nuit ou de l'app : début, fin, issue, quelques mots sans montant.

L'app demande une tâche (`request`) ; le planificateur, qui se réveille chaque minute, prend la
demande (`take_requested`) et lance la même commande que la nuit. Une demande « après les
sources » (« Tout actualiser ») attend que les actualisations des connexions soient finies et
que leurs fichiers aient eu le temps d'être importés. Une tâche d'actualisation forcée
(`DomainTask.connector`) n'attend pas le planificateur : c'est une demande aux collecteurs.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import timedelta
from typing import TypedDict

from sqlalchemy import Connection, Engine, text

from hub.core import collectors
from hub.core.context import HubContext
from hub.core.coredb import audit
from hub.core.domain import NightlyTasks
from hub.core.errors import Problem
from hub.kernel.clock import now_iso, parse_iso, utcnow
from hub.platform.logging import get_logger

log = get_logger("hub.tasks")

HUB = "hub"
HOUSEKEEPING = "hub.housekeeping"
SETTLE = timedelta(minutes=2)  # le temps que la boîte d'entrée importe ce qu'une collecte a déposé
SOURCES_MAX = timedelta(minutes=45)  # au-delà, les calculs partent même si une source traîne
STALE = timedelta(hours=3)  # commencé, jamais fini (conteneur arrêté) : plus « en cours »


@dataclass(frozen=True)
class Task:
    name: str  # `hub.backup`, `finance.strategies`
    domain: str  # `hub` pour l'entretien du hub
    label: str
    when: str  # en mots, pour l'app
    command: tuple[str, ...] = ()  # ce que le planificateur lance ; vide : collecteurs
    connector: str | None = None
    run: Callable[[], str] | None = field(default=None, compare=False)


# l'entretien du hub : les lignes de deploy/crontab (même commande, même heure)
CORE: tuple[Task, ...] = (
    Task(
        "hub.verify",
        HUB,
        "Contrôle d'intégrité",
        "chaque nuit 02:15",
        ("hub", "verify", "--notify"),
    ),
    Task("hub.backup", HUB, "Sauvegarde", "chaque nuit 02:30", ("hub", "backup", "--restic")),
    Task(
        "hub.backup_check",
        HUB,
        "Contrôle des sauvegardes",
        "le dimanche 04:00",
        ("hub", "backup-check"),
    ),
    Task("hub.health", HUB, "Santé du serveur", "chaque heure", ("hub", "ops", "health")),
    Task(
        HOUSEKEEPING,
        HUB,
        "Ménage de la nuit",
        "chaque nuit 03:00",
        ("hub", "task", "run", HOUSEKEEPING),
    ),
)


def domain_tasks(hub: HubContext) -> list[Task]:
    out: list[Task] = []
    for d in hub.registry:
        if not isinstance(d, NightlyTasks):
            continue
        for t in d.tasks():
            name = f"{d.name}.{t.id}"
            command = () if t.connector else ("hub", "task", "run", name)
            out.append(Task(name, d.name, t.label, t.when, command, t.connector, t.run))
    return out


def catalog(hub: HubContext) -> list[Task]:
    return [*CORE, *domain_tasks(hub)]


def find(hub: HubContext, name: str) -> Task:
    found = next((t for t in catalog(hub) if t.name == name), None)
    if found is None:
        raise Problem("task.unknown", f"tâche inconnue : {name}")
    return found


# --- passages ---------------------------------------------------------------------------------


class Note:
    """Ce que la tâche dit d'elle-même à la fin : quelques mots, jamais un montant."""

    text: str | None = None


def _exit_code(exc: BaseException) -> int:
    code = getattr(exc, "exit_code", None)  # typer.Exit
    if code is None and isinstance(exc, SystemExit):
        code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
    return 1 if code is None else int(code)


def _write(engine: Engine, sql: str, params: dict[str, str | None]) -> None:
    """Un passage noté ne doit jamais faire échouer la tâche (base pas encore migrée…)."""
    try:
        with engine.begin() as conn:
            conn.execute(text(sql), params)
    except Exception as exc:
        log.warning("task.unrecorded", task=params.get("t"), error=type(exc).__name__)


@contextmanager
def recorded(engine: Engine, name: str) -> Iterator[Note]:
    """Note le début et la fin d'une tâche ; une erreur ou un code de sortie non nul l'inscrit
    en échec, puis remonte telle quelle."""
    note = Note()
    _write(
        engine,
        "INSERT INTO task_runs (task, started_at) VALUES (:t, :at) "
        "ON CONFLICT (task) DO UPDATE SET started_at = :at",
        {"t": name, "at": now_iso()},
    )
    outcome = "failed"
    try:
        yield note
        outcome = "ok"
    except BaseException as exc:
        if _exit_code(exc) == 0:
            outcome = "ok"
        raise
    finally:
        _write(
            engine,
            "UPDATE task_runs SET ended_at = :at, outcome = :o, summary = :s WHERE task = :t",
            {"t": name, "at": now_iso(), "o": outcome, "s": (note.text or "")[:120] or None},
        )


def run_domain_task(hub: HubContext, task: Task) -> str:
    """Un morceau de la nuit d'un domaine, lancé seul (`hub task run`) : puis les cartes et
    notifications qu'il a demandées, comme la nuit."""
    from hub.core import proposal_events

    if task.run is None:
        raise Problem("task.unknown", f"{task.name} se lance depuis l'app (collecteurs)")
    with recorded(hub.core.engine, task.name) as note:
        note.text = task.run()
    proposal_events.sync_events(hub)
    return note.text or ""


def run_domain_tasks(hub: HubContext) -> list[str]:
    """Chaque morceau de la nuit des domaines, dans l'ordre, chacun noté ; un échec est journalisé
    et n'arrête pas les suivants. Rend les tâches en échec."""
    failed = []
    for task in domain_tasks(hub):
        if task.run is None:
            continue
        try:
            with recorded(hub.core.engine, task.name) as note:
                note.text = task.run()
        except Exception as exc:
            log.error("task.failed", task=task.name, error=type(exc).__name__)
            failed.append(task.name)
    return failed


# --- demandes depuis l'app ----------------------------------------------------------------------


def _connections(conn: Connection, connector: str) -> list[collectors.State]:
    return [
        s
        for s in collectors.list_all(conn)
        if s.connector == connector and s.ready and s.mode == "enabled"
    ]


def request(
    conn: Connection, hub: HubContext, name: str, by: str, *, after_sources: bool = False
) -> None:
    """Une tâche demandée depuis l'app : prise par le planificateur dans la minute. Une demande
    déjà posée reste ; un geste à la main lève son attente des sources."""
    task = find(hub, name)
    if task.connector:
        states = _connections(conn, task.connector)
        if not states:
            raise Problem("task.no_source")
        for s in states:
            collectors.request_run(conn, s.name, by)
            conn.execute(  # le run relit aussi ce que le flux garde d'habitude pour plus tard
                text(
                    "UPDATE collector_state SET force_requested_at = coalesce("
                    "force_requested_at, :at) WHERE collector = :c"
                ),
                {"c": s.name, "at": now_iso()},
            )
        audit(conn, by, "task.requested", f"task:{name}", "ok")
        return
    conn.execute(
        text(
            "INSERT INTO task_runs (task, requested_at, requested_by, after_sources) "
            "VALUES (:t, :at, :by, :a) ON CONFLICT (task) DO UPDATE SET "
            "requested_at = coalesce(task_runs.requested_at, :at), requested_by = :by, "
            "after_sources = CASE WHEN task_runs.requested_at IS NULL THEN :a "
            "ELSE min(task_runs.after_sources, :a) END"
        ),
        {"t": name, "at": now_iso(), "by": by, "a": int(after_sources)},
    )
    audit(conn, by, "task.requested", f"task:{name}", "ok")


def refresh_all(conn: Connection, hub: HubContext, by: str) -> None:
    """« Tout actualiser » : chaque connexion prête et active, puis, quand elles ont fini, les
    calculs des domaines (pas l'entretien, pas les actualisations forcées)."""
    collectors.request_run_all(conn, by)
    for t in domain_tasks(hub):
        if t.run is not None:
            request(conn, hub, t.name, by, after_sources=True)


def sources_busy(conn: Connection) -> bool:
    """Une connexion a une actualisation en attente ou en cours, ou vient de finir (ses fichiers
    sont peut-être encore dans la boîte d'entrée)."""
    pending = conn.execute(
        text("SELECT count(*) FROM collector_state WHERE run_requested_at IS NOT NULL")
    ).scalar_one()
    if pending:
        return True
    last = conn.execute(text("SELECT max(ended_at) FROM collector_runs")).scalar_one()
    return bool(last) and utcnow() - parse_iso(last) < SETTLE


def take_requested(engine: Engine, hub: HubContext) -> list[tuple[str, ...]]:
    """Les commandes à lancer maintenant, dans l'ordre du catalogue ; leurs demandes sont
    effacées (une demande se prend une fois)."""
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                "SELECT task, requested_at, after_sources FROM task_runs "
                "WHERE requested_at IS NOT NULL"
            )
        ).fetchall()
        if not rows:
            return []
        busy = any(r.after_sources for r in rows) and sources_busy(conn)
        now = utcnow()
        ready = {
            r.task
            for r in rows
            if not (r.after_sources and busy and now - parse_iso(r.requested_at) < SOURCES_MAX)
        }
        out = []
        for t in catalog(hub):
            if t.name in ready and t.command:
                out.append(t.command)
        for name in ready:
            conn.execute(
                text("UPDATE task_runs SET requested_at = NULL WHERE task = :t"), {"t": name}
            )
    return out


class Status(TypedDict):
    requested: bool
    running: bool
    after_sources: bool
    available: bool
    started_at: str | None
    ended_at: str | None
    outcome: str | None
    summary: str | None


class Row(Status):
    name: str
    domain: str
    label: str
    when: str


# --- état, pour l'app --------------------------------------------------------------------------


def _running(started: str | None, ended: str | None) -> bool:
    if not started or (ended and ended >= started):
        return False
    return utcnow() - parse_iso(started) < STALE


def _from_collectors(all_states: list[collectors.State], connector: str) -> Status:
    states = [s for s in all_states if s.connector == connector]
    runs = [s.last_run for s in states if s.last_run and s.last_run.get("kind") == "run"]
    last = max(runs, key=lambda r: r["ended_at"], default=None)
    ok = last is not None and last["outcome"] in collectors.SUCCESS
    return {
        "requested": any(s.run_requested_at for s in states),
        "running": False,
        "after_sources": False,
        "available": any(s.ready and s.mode == "enabled" for s in states),
        "started_at": last["started_at"] if last else None,
        "ended_at": last["ended_at"] if last else None,
        "outcome": None if last is None else ("ok" if ok else "failed"),
        "summary": None,
    }


def status(conn: Connection, hub: HubContext) -> list[Row]:
    # l'écriture d'abord (list_all pose l'état manquant) : une transaction qui lit puis écrit
    # ne peut pas attendre le verrou (core.collectors)
    states = collectors.list_all(conn)
    rows = {r.task: r for r in conn.execute(text("SELECT * FROM task_runs")).fetchall()}
    out: list[Row] = []
    for t in catalog(hub):
        r = rows.get(t.name)
        st: Status = (
            _from_collectors(states, t.connector)
            if t.connector
            else {
                "requested": bool(r and r.requested_at),
                "running": r is not None and _running(r.started_at, r.ended_at),
                "available": True,
                "after_sources": bool(r and r.requested_at and r.after_sources),
                "started_at": r.started_at if r else None,
                "ended_at": r.ended_at if r else None,
                "outcome": r.outcome if r else None,
                "summary": r.summary if r else None,
            }
        )
        out.append(Row(name=t.name, domain=t.domain, label=t.label, when=t.when, **st))
    return out
