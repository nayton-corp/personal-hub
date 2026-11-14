"""Tâches planifiées relancées à la main (core.tasks) : catalogue aligné sur la crontab, passages
notés, la nuit en morceaux, demandes de l'app prises par le planificateur (après les sources pour
« Tout actualiser »), actualisation forcée des collecteurs, routes de l'app."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from datetime import timedelta
from pathlib import Path

import pytest
import typer
from fastapi.testclient import TestClient
from sqlalchemy import text

from hub.api.app import create_app
from hub.core import collectors, connections, tasks
from hub.core.context import HubContext
from hub.core.domain import DomainTask
from hub.core.errors import Problem
from hub.core.maintenance import nightly
from hub.core.registry import Registry
from hub.kernel.clock import iso, now_iso, utcnow
from hub.platform.cron import REPORTED, parse, serve_requested
from hub.platform.settings import Settings
from tests.conftest import bearer
from tests.finance.test_finance_api import app_session
from tests.support.demo_domain import DemoDomain

ROOT = Path(__file__).resolve().parents[1]


class TaskDomain(DemoDomain):
    """Le domaine factice, avec une nuit en morceaux : un qui marche, un qui échoue, et une
    actualisation forcée du collecteur des cours."""

    def __init__(self, data_dir: Path) -> None:
        super().__init__(data_dir)
        self.ran: list[str] = []
        self.fail = False

    def _one(self) -> str:
        self.ran.append("one")
        return "2 choses faites"

    def _boom(self) -> str:
        self.ran.append("boom")
        if self.fail:
            raise RuntimeError("en panne")
        return "rien de neuf"

    def tasks(self) -> Sequence[DomainTask]:
        return (
            DomainTask("one", "Un calcul", self._one),
            DomainTask("boom", "Un calcul fragile", self._boom),
            DomainTask("fresh", "Relire les cours", connector="market", when="chaque jour"),
        )


@pytest.fixture
def thub(settings: Settings) -> Iterator[HubContext]:
    ctx = HubContext.build(settings, Registry([TaskDomain(settings.paths.data)]))
    ctx.migrate_all()
    yield ctx
    ctx.dispose()


@pytest.fixture
def dom(thub: HubContext) -> TaskDomain:
    d = thub.registry.get("demo")
    assert isinstance(d, TaskDomain)
    return d


def _rows(hub: HubContext) -> dict[str, tasks.Row]:
    with hub.core.engine.connect() as conn:
        return {t["name"]: t for t in tasks.status(conn, hub)}


def test_the_hub_tasks_are_the_crontab_lines() -> None:
    """Chaque tâche d'entretien est une ligne de deploy/crontab, à l'heure que l'app affiche ;
    le ménage est la commande `hub nightly`, découpée."""
    jobs = {j.command: j for j in parse((ROOT / "deploy" / "crontab").read_text())}
    for t in tasks.CORE:
        command = ("hub", "nightly") if t.name == tasks.HOUSEKEEPING else t.command
        job = jobs[command]
        if t.when != "chaque heure":
            hour, minute = t.when.rsplit(" ", 1)[-1].split(":")
            assert (min(job.hours), min(job.minutes)) == (int(hour), int(minute)), t.name
    assert {t.name for t in tasks.CORE} == {
        "hub.verify",
        "hub.backup",
        "hub.backup_check",
        "hub.health",
        tasks.HOUSEKEEPING,
    }


def test_catalog_adds_the_domain_pieces(thub: HubContext) -> None:
    names = [t.name for t in tasks.catalog(thub)]
    assert names[-3:] == ["demo.one", "demo.boom", "demo.fresh"]
    fresh = tasks.find(thub, "demo.fresh")
    assert fresh.command == ()
    assert fresh.connector == "market"
    assert tasks.find(thub, "demo.one").command == ("hub", "task", "run", "demo.one")
    with pytest.raises(Problem) as e:
        tasks.find(thub, "demo.nope")
    assert e.value.type == "task.unknown"


def test_a_passage_is_recorded_ok_or_failed(thub: HubContext) -> None:
    with tasks.recorded(thub.core.engine, "hub.backup") as note:
        assert _rows(thub)["hub.backup"]["running"] is True
        note.text = "3 bases copiées"
    row = _rows(thub)["hub.backup"]
    assert (row["outcome"], row["summary"], row["running"]) == ("ok", "3 bases copiées", False)
    with pytest.raises(typer.Exit), tasks.recorded(thub.core.engine, "hub.verify"):
        raise typer.Exit(0)  # une commande qui sort proprement
    assert _rows(thub)["hub.verify"]["outcome"] == "ok"
    with pytest.raises(typer.Exit), tasks.recorded(thub.core.engine, "hub.verify"):
        raise typer.Exit(REPORTED)
    assert _rows(thub)["hub.verify"]["outcome"] == "failed"
    with pytest.raises(ValueError, match="x"), tasks.recorded(thub.core.engine, "hub.health"):
        raise ValueError("x")
    assert _rows(thub)["hub.health"]["outcome"] == "failed"


def test_an_unfinished_passage_is_not_running_forever(thub: HubContext) -> None:
    old = iso(utcnow() - timedelta(hours=4))
    with thub.core.engine.begin() as conn:
        conn.execute(
            text("INSERT INTO task_runs (task, started_at) VALUES ('hub.backup', :s)"), {"s": old}
        )
    assert _rows(thub)["hub.backup"]["running"] is False


def test_recording_never_breaks_the_task(settings: Settings) -> None:
    """Une base pas encore migrée (verify avant une migration) : la tâche passe quand même."""
    ctx = HubContext.build(settings, Registry([]))
    with tasks.recorded(ctx.core.engine, "hub.verify") as note:
        note.text = "intact"
    ctx.dispose()


def test_nightly_records_each_piece_and_keeps_going(thub: HubContext, dom: TaskDomain) -> None:
    result = nightly(thub)
    assert dom.ran == ["one", "boom"]
    assert dom.nightly_runs == 0  # une nuit en morceaux remplace nightly()
    rows = _rows(thub)
    assert rows["demo.one"]["summary"] == "2 choses faites"
    assert rows[tasks.HOUSEKEEPING]["outcome"] == "ok"
    assert result["expired"] == 0
    dom.fail = True
    dom.ran.clear()
    with pytest.raises(RuntimeError, match=r"demo\.boom"):
        nightly(thub)
    assert dom.ran == ["one", "boom"]
    assert _rows(thub)["demo.boom"]["outcome"] == "failed"
    assert _rows(thub)["demo.one"]["outcome"] == "ok"


def test_a_domain_without_pieces_keeps_its_nightly(hub: HubContext, demo: DemoDomain) -> None:
    nightly(hub)
    assert demo.nightly_runs == 1
    assert [t.name for t in tasks.catalog(hub)] == [t.name for t in tasks.CORE]


def test_one_piece_runs_alone(thub: HubContext, dom: TaskDomain) -> None:
    assert tasks.run_domain_task(thub, tasks.find(thub, "demo.one")) == "2 choses faites"
    assert dom.ran == ["one"]
    with pytest.raises(Problem):
        tasks.run_domain_task(thub, tasks.find(thub, "demo.fresh"))


def _take(hub: HubContext) -> list[tuple[str, ...]]:
    return tasks.take_requested(hub.core.engine, hub)


def test_a_request_is_taken_once_in_catalog_order(thub: HubContext) -> None:
    with thub.core.engine.begin() as conn:
        tasks.request(conn, thub, "demo.one", "app")
        tasks.request(conn, thub, "hub.backup", "app")
        tasks.request(conn, thub, "hub.backup", "app")  # déjà demandée : une seule fois
    assert _rows(thub)["hub.backup"]["requested"] is True
    assert _take(thub) == [("hub", "backup", "--restic"), ("hub", "task", "run", "demo.one")]
    assert _take(thub) == []
    assert _rows(thub)["hub.backup"]["requested"] is False


def _connection(hub: HubContext, name: str = "market") -> None:
    with hub.core.engine.begin() as conn:
        connections.create(conn, name, "market", "system:test")


def _ran(hub: HubContext, name: str = "market", ended: str | None = None) -> None:
    at = ended or now_iso()
    with hub.core.engine.begin() as conn:
        collectors.record(conn, name, collectors.Run("run", "ok", at, at), "system:test")


def test_refresh_all_waits_for_the_sources(thub: HubContext) -> None:
    """« Tout actualiser » : les connexions d'abord ; les calculs partent quand elles ont fini
    et que leurs fichiers ont eu le temps d'être importés."""
    _connection(thub)
    with thub.core.engine.begin() as conn:
        tasks.refresh_all(conn, thub, "app")
        assert collectors.get(conn, "market").run_requested_at is not None
    rows = _rows(thub)
    assert rows["demo.one"]["after_sources"] is True
    assert rows["hub.backup"]["requested"] is False  # pas l'entretien
    assert rows["demo.fresh"]["requested"] is True  # le run normal, pas forcé
    assert _take(thub) == []  # la connexion n'a pas fini
    _ran(thub)
    assert _take(thub) == []  # elle vient de finir : la boîte d'entrée importe encore
    with thub.core.engine.begin() as conn:
        conn.execute(
            text("UPDATE collector_runs SET ended_at = :e"),
            {"e": iso(utcnow() - timedelta(minutes=3))},
        )
    assert _take(thub) == [("hub", "task", "run", "demo.one"), ("hub", "task", "run", "demo.boom")]


def test_a_manual_request_skips_the_wait_and_a_stuck_source_does_not_block(
    thub: HubContext,
) -> None:
    _connection(thub)
    with thub.core.engine.begin() as conn:
        tasks.refresh_all(conn, thub, "app")
        tasks.request(conn, thub, "demo.one", "app")  # « Actualiser » sur la ligne
    assert _take(thub) == [("hub", "task", "run", "demo.one")]
    with thub.core.engine.begin() as conn:
        conn.execute(
            text("UPDATE task_runs SET requested_at = :r WHERE requested_at IS NOT NULL"),
            {"r": iso(utcnow() - timedelta(hours=1))},
        )
    assert _take(thub) == [("hub", "task", "run", "demo.boom")]


def test_a_connector_piece_forces_the_collectors(thub: HubContext) -> None:
    with thub.core.engine.begin() as conn, pytest.raises(Problem) as e:
        tasks.request(conn, thub, "demo.fresh", "app")
    assert e.value.type == "task.no_source"
    assert _rows(thub)["demo.fresh"]["available"] is False
    _connection(thub)
    with thub.core.engine.begin() as conn:
        tasks.request(conn, thub, "demo.fresh", "app")
        state = collectors.get(conn, "market").public()
    assert state["run_requested"]
    assert state["force_requested"]
    assert _rows(thub)["demo.fresh"]["requested"] is True
    assert _take(thub) == []  # rien pour le planificateur : c'est le collecteur qui relit
    _ran(thub)
    row = _rows(thub)["demo.fresh"]
    assert (row["requested"], row["outcome"]) == (False, "ok")
    with thub.core.engine.begin() as conn:
        assert collectors.get(conn, "market").public()["force_requested"] is False


def test_the_scheduler_runs_what_the_app_asked() -> None:
    ran: list[tuple[str, ...]] = []
    failed: list[tuple[tuple[str, ...], int]] = []

    def runner(command: tuple[str, ...]) -> int:
        ran.append(command)
        return 1 if command[1] == "backup" else 0

    out = serve_requested(
        lambda: [("hub", "verify"), ("hub", "backup")],
        runner,
        lambda c, code: failed.append((c, code)),
    )
    assert out == [(("hub", "verify"), 0), (("hub", "backup"), 1)]
    assert failed == [(("hub", "backup"), 1)]

    def unreadable() -> list[tuple[str, ...]]:
        raise RuntimeError("database is locked")

    assert serve_requested(unreadable, runner) == []


def test_app_routes(thub: HubContext, make_token) -> None:  # type: ignore[no-untyped-def]
    with TestClient(create_app(thub), base_url="https://hub.example.ts.net") as client:
        assert client.get("/api/tasks").status_code == 401
        assert client.get("/api/tasks", headers=bearer(make_token("demo:read"))).status_code == 403
        app_session(thub, client)
        items = {t["name"]: t for t in client.get("/api/tasks").json()["items"]}
        assert items["hub.backup"]["when"] == "chaque nuit 02:30"
        assert items["demo.one"]["outcome"] is None
        r = client.post("/api/tasks/demo.one/run")
        assert r.status_code == 200
        assert {t["name"]: t["requested"] for t in r.json()["items"]}["demo.one"] is True
        assert client.post("/api/tasks/demo.nope/run").status_code == 404
        assert client.post("/api/tasks/demo.fresh/run").status_code == 409
        r = client.post("/api/tasks/refresh")
        assert {t["name"]: t["after_sources"] for t in r.json()["items"]}["demo.boom"] is True
