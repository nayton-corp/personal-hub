"""Boucle planifiée, contrôles demandés, dépôt atomique et formes de fichiers, client du hub."""

from __future__ import annotations

import io
import json
import os
import time
import urllib.error
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from hub.collectors import dropbox
from hub.collectors.base import CollectorConfig, Failure, Kind, Memory, Result
from hub.collectors.browser import Selectors, purge_diag
from hub.collectors.client import HubClient, HubUnavailable
from hub.collectors.runtime import Assigned, Env, assigned, due, execute, tick
from hub.core import connectors
from tests.collectors.conftest import FakeHub
from tests.collectors.fakebank import camt_file
from tests.factories.camt import zipped

TZ = ZoneInfo("Europe/Zurich")
MONDAY_0730 = datetime(2026, 10, 26, 7, 30, tzinfo=TZ)


def _env(tmp_path: Path, hub: Any, name: str = "bcf") -> Env:
    return Env(name, CollectorConfig(home=tmp_path / "c"), {}, tmp_path / "inbox", hub)


def _schedule(name: str) -> str:
    spec = connectors.get(name)
    assert spec is not None
    return spec.schedule


def test_schedules() -> None:
    assert due(_schedule("bcf"), MONDAY_0730)
    assert not due(_schedule("bcf"), MONDAY_0730 + timedelta(days=5))  # samedi
    assert due(_schedule("viac"), datetime(2026, 11, 1, 9, 0, tzinfo=TZ))  # dimanche
    syncs = [
        h
        for h in range(24)
        if due(_schedule("enable_banking"), MONDAY_0730.replace(hour=h, minute=15))
    ]
    assert len(syncs) <= 4


BCF = Assigned("bcf", "bcf", "BCF", _schedule("bcf"), {}, None)


def _runner(log: list[tuple[str, Kind]]):  # type: ignore[no-untyped-def]
    def run(env: Env, kind: Kind) -> Result:
        log.append((env.name, kind))
        return Result("ok")

    return run


@pytest.mark.parametrize(
    ("mode", "check", "at", "expected"),
    [
        ("enabled", False, MONDAY_0730, [("bcf", "run")]),
        ("degraded", False, MONDAY_0730, []),
        ("disabled", False, MONDAY_0730, []),
        ("enabled", False, MONDAY_0730 + timedelta(minutes=1), []),
        ("degraded", True, MONDAY_0730 + timedelta(minutes=1), [("bcf", "check")]),
    ],
)
def test_tick(tmp_path: Path, mode: str, check: bool, at: datetime, expected: list[Any]) -> None:
    hub = FakeHub(mode=mode, check_requested=check)
    log: list[tuple[str, Kind]] = []
    tick(
        lambda item: _env(tmp_path, hub, item.id),
        [BCF],
        hub,  # type: ignore[arg-type]
        at,
        poll_checks=True,
        runner=_runner(log),
    )
    assert log == expected


def test_tick_without_hub_runs_nothing(tmp_path: Path) -> None:
    class Down(FakeHub):
        def state(self, name: str) -> dict[str, Any]:
            raise HubUnavailable("down")

    log: list[tuple[str, Kind]] = []
    down = Down()
    tick(
        lambda item: _env(tmp_path, down, item.id),
        [BCF],
        down,  # type: ignore[arg-type]
        MONDAY_0730,
        poll_checks=True,
        runner=_runner(log),
    )
    assert log == []


def test_tick_reports_a_connection_it_cannot_open(tmp_path: Path) -> None:
    """Secrets illisibles ou réglage invalide : un run « unknown » déclaré, pas de flux."""
    hub = FakeHub()
    log: list[tuple[str, Kind]] = []

    def broken(_item: Assigned) -> Env:
        raise ValueError("secrets")

    done = tick(broken, [BCF], hub, MONDAY_0730, poll_checks=False, runner=_runner(log))  # type: ignore[arg-type]
    assert (done, log) == ([("bcf", "run", "unknown")], [])
    assert hub.runs == [("bcf", "run", "unknown")]


def test_assigned_connections(tmp_path: Path) -> None:
    raw = {"id": "n26", "connector": "enable_banking", "schedule": None, "secrets": None}

    class Hub(FakeHub):
        def connections(self, runner: str) -> list[dict[str, Any]]:
            assert runner == "api"
            return [raw]

    class Down(FakeHub):
        def connections(self, runner: str) -> list[dict[str, Any]]:
            raise HubUnavailable("down")

    (item,) = assigned(Hub(), "api")  # type: ignore[arg-type,misc]
    assert (item.id, item.label, item.settings) == ("n26", "n26", {})
    assert assigned(Down(), "api") is None  # type: ignore[arg-type]


def test_execute_maps_exceptions_and_reports(tmp_path: Path) -> None:
    hub = FakeHub()
    env = _env(tmp_path, hub)

    def boom(_env: Env, _kind: Kind) -> Result:
        raise KeyError("x")

    def fail(_env: Env, _kind: Kind) -> Result:
        raise Failure("selector_missing", "export.button")

    assert execute(env, "run", boom).detail == "exception:keyerror"
    assert execute(env, "run", fail).outcome == "selector_missing"
    assert hub.runs == [("bcf", "run", "unknown"), ("bcf", "run", "selector_missing")]


# --- formes de fichiers et dépôt --------------------------------------------------------------


def test_file_shapes() -> None:
    camt = camt_file(datetime(2026, 10, 1).date())
    assert dropbox.is_camt_export(camt)
    assert dropbox.is_camt_export(zipped({"a.xml": camt, "b.xml": camt}))
    assert not dropbox.is_camt_export(zipped({"a.xml": camt, "lisez.txt": b"x"}))
    assert not dropbox.is_camt_export(b"<html/>")
    assert not dropbox.is_camt_export(
        b'<!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]><x>&e;</x>'
    )
    assert not dropbox.is_camt_export(b"PK\x03\x04 pas un zip")
    assert dropbox.is_pdf(b"%PDF-1.7\n...\n%%EOF\n")
    assert not dropbox.is_pdf(b"%PDF-1.7 tronque")
    assert dropbox.is_revolut_json(
        json.dumps({"format": "hub.revolut.v1", "account": {}, "transactions": []}).encode()
    )
    assert not dropbox.is_revolut_json(b"{")


def test_drop_is_atomic_and_remembers(tmp_path: Path) -> None:
    memory = Memory(tmp_path / "m.json")
    inbox = dropbox.Inbox(tmp_path / "inbox", memory)
    assert inbox.drop("a b/../c.pdf", b"%PDF-1\n%%EOF", dropbox.is_pdf, step="s")
    assert not inbox.drop("autre.pdf", b"%PDF-1\n%%EOF", dropbox.is_pdf, step="s")
    files = [p for p in (tmp_path / "inbox").iterdir() if p.is_file()]
    assert len(files) == 1
    assert "/" not in files[0].name
    assert files[0].name.endswith("a-b-..-c.pdf")
    memory.save()
    assert oct(os.stat(tmp_path / "m.json").st_mode)[-3:] == "600"
    assert Memory(tmp_path / "m.json").seen() == memory.seen()
    old = time.time() - 3600
    stale = inbox.tmp / "reste.part"
    stale.write_bytes(b"x")
    os.utime(stale, (old, old))
    assert inbox.clean_tmp(datetime.now(TZ) - timedelta(minutes=5)) == 1


def test_same_name_in_the_same_second_keeps_both_files(tmp_path: Path) -> None:
    # deux versements du même jour, un par portefeuille, portent le même nom chez VIAC
    inbox = dropbox.Inbox(tmp_path / "inbox", Memory(tmp_path / "m.json"))
    inbox.stamp = lambda: "20261028T063517"  # type: ignore[method-assign]
    assert inbox.drop("Versement.pdf", b"%PDF-1\nA\n%%EOF", dropbox.is_pdf, step="s")
    assert inbox.drop("Versement.pdf", b"%PDF-1\nB\n%%EOF", dropbox.is_pdf, step="s")
    files = sorted(p.read_bytes() for p in (tmp_path / "inbox").iterdir() if p.is_file())
    assert files == [b"%PDF-1\nA\n%%EOF", b"%PDF-1\nB\n%%EOF"]


def test_selectors_and_purge(tmp_path: Path) -> None:
    path = tmp_path / "s.toml"
    path.write_text('[site]\nurl = "a"\n[x]\nb = "c"\n[clicks]\nallowed = ["x.b"]\n')
    sel = Selectors.load(path, {"url": "z"})
    assert sel.site("url") == "z"
    assert sel.names() == ["x.b"]
    assert sel.allowed == {"x.b"}
    with pytest.raises(KeyError):
        sel.get("x.absent")
    diag = tmp_path / "diag"
    diag.mkdir()
    old_file = diag / "old.png"
    old_file.write_bytes(b"x")
    os.utime(old_file, (time.time() - 10 * 86_400,) * 2)
    (diag / "new.png").write_bytes(b"x")
    assert purge_diag(diag, 7) == 1
    assert purge_diag(tmp_path / "absent", 7) == 0


# --- client du hub ----------------------------------------------------------------------------


class _Response(io.BytesIO):
    status = 200

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_a: object) -> None:
        pass


def test_hub_client(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[str, str, Any]] = []

    def fake_urlopen(request: Any, timeout: float) -> _Response:
        body = json.loads(request.data) if request.data else None
        seen.append((request.get_method(), request.full_url, body))
        assert request.headers["Authorization"] == "Bearer hub_x"
        if request.full_url.endswith("/links/s"):
            return _Response(json.dumps({"state": "s", "code": "c"}).encode())
        if request.full_url.endswith("/links"):
            return _Response(json.dumps({"state": "s", "expires_at": "t"}).encode())
        if request.full_url.endswith("/notify"):
            return _Response(b'{"sent": true}')
        return _Response(b'{"mode": "enabled"}')

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    c = HubClient("http://api:8710/", "hub_x")
    assert c.state("bcf") == {"mode": "enabled"}
    c.report("bcf", "run", Result("ok", 1), "a", "b")
    assert seen[-1][2]["files"] == 1
    assert c.notify("bcf", "auth_pending") is True
    assert c.register_link("revolut", "s") == "t"
    assert c.take_link("revolut", "s") == "c"
    assert seen[0][1] == "http://api:8710/api/collectors/bcf"

    def refuse(request: Any, timeout: float) -> _Response:
        raise urllib.error.HTTPError(request.full_url, 403, "no", {}, None)  # type: ignore[arg-type]

    monkeypatch.setattr("urllib.request.urlopen", refuse)
    pauses: list[int] = []
    c.pause = pauses.append  # type: ignore[method-assign]
    with pytest.raises(HubUnavailable):
        c.state("bcf")
    assert c.notify("bcf", "auth_pending") is False
    assert pauses == []  # un refus 4xx ne se réessaie pas

    # « database is locked » côté hub : deux 500 puis la réponse
    calls: list[str] = []

    def locked_then_ok(request: Any, timeout: float) -> _Response:
        calls.append(request.full_url)
        if len(calls) < 3:
            raise urllib.error.HTTPError(request.full_url, 500, "locked", {}, None)  # type: ignore[arg-type]
        return _Response(json.dumps({"state": "s", "code": "c"}).encode())

    monkeypatch.setattr("urllib.request.urlopen", locked_then_ok)
    assert c.take_link("revolut", "s") == "c"
    assert pauses == [1, 3]
    calls.clear()
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda r, timeout: (_ for _ in ()).throw(
            urllib.error.HTTPError(r.full_url, 500, "x", {}, None)  # type: ignore[arg-type]
        ),
    )
    with pytest.raises(HubUnavailable):
        c.state("bcf")


# --- consentement demandé depuis l'app (G5) --------------------------------------------------

EB = Assigned("revolut", "enable_banking", "Revolut", _schedule("enable_banking"), {}, None)


def test_tick_hands_a_requested_link_to_the_linker(tmp_path: Path) -> None:
    hub = FakeHub(link_requested=True)
    started: list[str] = []
    log: list[tuple[str, Kind]] = []
    done = tick(
        lambda item: _env(tmp_path, hub, item.id),
        [EB, BCF],
        hub,  # type: ignore[arg-type]
        MONDAY_0730 + timedelta(minutes=1),
        poll_checks=True,
        runner=_runner(log),
        linker=lambda env: started.append(env.name),
    )
    assert started == ["revolut"]  # BCF ne se lie pas : rien ne part pour elle
    assert done == [("revolut", "link", "started")]
    assert log == []


def test_link_now_posts_the_url_then_clears_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hub.collectors import runtime
    from hub.collectors.revolut import flow

    hub = FakeHub()
    seen: list[str] = []

    def fake_link(env: Env, redirect: str, show: Any, **_kw: Any) -> Result:
        seen.append(redirect)
        show("https://bank.example.invalid/auth")
        return Result("ok", 2)

    monkeypatch.setattr(flow, "link", fake_link)
    env = _env(tmp_path, hub, "revolut")
    assert runtime.link_now(env, "https://hub.example/cb").outcome == "ok"
    assert seen == ["https://hub.example/cb"]
    assert hub.link_urls == ["https://bank.example.invalid/auth", None]
    assert hub.runs == [("revolut", "check", "ok")]

    def refused(*_a: Any, **_kw: Any) -> Result:
        raise Failure("auth_pending_timeout", "link.callback")

    monkeypatch.setattr(flow, "link", refused)
    thread = runtime.start_link(env, "https://hub.example/cb")
    assert thread is not None
    assert runtime.start_link(env, "https://hub.example/cb") is None or not thread.is_alive()
    thread.join(5)
    assert "revolut" not in runtime.LINKING
    assert hub.runs[-1] == ("revolut", "check", "auth_pending_timeout")
    assert hub.link_urls[-1] is None
