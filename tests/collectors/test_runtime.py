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
from hub.collectors.runtime import Env, due, execute, tick
from tests.collectors.conftest import FakeHub
from tests.collectors.fakebank import camt_file
from tests.factories.camt import zipped

TZ = ZoneInfo("Europe/Zurich")
MONDAY_0730 = datetime(2026, 10, 26, 7, 30, tzinfo=TZ)


def _env(tmp_path: Path, hub: Any, name: str = "bcf") -> Env:
    return Env(name, CollectorConfig(home=tmp_path / "c"), {}, tmp_path / "inbox", hub)


def test_schedules() -> None:
    cfg = CollectorConfig()
    assert due(cfg.schedules["bcf"], MONDAY_0730)
    assert not due(cfg.schedules["bcf"], MONDAY_0730 + timedelta(days=5))  # samedi
    assert due(cfg.schedules["viac"], datetime(2026, 11, 1, 9, 0, tzinfo=TZ))  # dimanche
    revolut = [
        h
        for h in range(24)
        if due(cfg.schedules["revolut"], MONDAY_0730.replace(hour=h, minute=15))
    ]
    assert len(revolut) <= 4


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
        lambda n: _env(tmp_path, hub, n),
        ["bcf"],
        CollectorConfig(),
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
    tick(
        lambda n: _env(tmp_path, Down(), n),
        ["bcf"],
        CollectorConfig(),
        MONDAY_0730,
        poll_checks=True,
        runner=_runner(log),
    )
    assert log == []


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
    with pytest.raises(HubUnavailable):
        c.state("bcf")
    assert c.notify("bcf", "auth_pending") is False
