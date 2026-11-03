"""Une route `async` ne bloque jamais la boucle d'évènements (audit M13) : un seul worker sert
l'API, un import ou une phrase dite à l'orbe gèlerait tout. Dans une route `async`, un port
synchrone (`host.…`, `hub_ctx.…`) s'appelle par `run_in_threadpool`, et le corps se lit en flux
(`hub.core.body.read_body`), jamais par `request.body()`."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASYNC_DEF = re.compile(r"^(\s*)async def (\w+)")
PORT_CALL = re.compile(r"\b(host|hub_ctx)\.(?!settings\b|core\b|registry\b)\w+(\.\w+)*\(")
WHOLE_BODY = re.compile(r"await request\.body\(\)")


def routes() -> list[Path]:
    found = (
        sorted(ROOT.glob("hub/api/routes_*.py"))
        + sorted(ROOT.glob("hub/domains/*/api.py"))
        + sorted(ROOT.glob("hub/domains/*/*/interface/api*.py"))
    )
    assert found
    return found


def async_bodies(source: str) -> list[tuple[str, list[str]]]:
    """(nom, lignes du corps) de chaque fonction `async def`."""
    out: list[tuple[str, list[str]]] = []
    lines = source.splitlines()
    i = 0
    while i < len(lines):
        m = ASYNC_DEF.match(lines[i])
        if not m:
            i += 1
            continue
        indent, name = len(m.group(1)), m.group(2)
        body: list[str] = []
        i += 1
        while i < len(lines):
            line = lines[i]
            bare = line.strip()
            if bare and (len(line) - len(line.lstrip())) <= indent and not bare.startswith(")"):
                break
            body.append(line)
            i += 1
        out.append((name, body))
    return out


def offences(source: str) -> list[str]:
    out = []
    for name, body in async_bodies(source):
        for line in body:
            if PORT_CALL.search(line) and "run_in_threadpool(" not in line:
                out.append(f"{name}: {line.strip()}")
            if WHOLE_BODY.search(line):
                out.append(f"{name}: corps lu d'un bloc, lire en flux (read_body)")
    return out


def test_async_routes_never_block_the_loop() -> None:
    found = {str(p.relative_to(ROOT)): offences(p.read_text()) for p in routes()}
    assert {k: v for k, v in found.items() if v} == {}


def test_the_rule_catches_what_it_should() -> None:
    bad = (
        "async def upload(request):\n    body = await request.body()\n"
        "    host.importer.receive(body)\n"
    )
    assert len(offences(bad)) == 2
    good = (
        "async def upload(request):\n    body = await read_body(request, 1)\n"
        "    await run_in_threadpool(host.importer.receive, body)\n\n"
        "def sync(host):\n    host.a.b()\n"
    )
    assert offences(good) == []
