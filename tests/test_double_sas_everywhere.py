"""Toute écriture d'un domaine passe par le Double Sas (audit du 2026-11-03, R2) : aucune
route HTTP d'un domaine n'ouvre de transaction d'écriture ni n'exécute INSERT, UPDATE ou DELETE.
Un geste de l'app est une proposition (`*_kinds.py`), validée par passkey, annulable ; une
lecture (GET) n'écrit pas dans la requête (un rafraîchissement part en tâche de fond). Les
routes du cœur qui portent le Double Sas lui-même (propositions, sessions, passkeys, passages
de collecteurs, profil) restent les seules à écrire."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WRITES = [
    re.compile(r"\bbegin_immediate\("),
    re.compile(r"\.begin\(\)"),
    re.compile(r"\b(INSERT\s+INTO|UPDATE\s+\w+\s+SET|DELETE\s+FROM)\b", re.I),
]


def domain_routes() -> list[Path]:
    found = sorted(ROOT.glob("hub/domains/*/api.py")) + sorted(
        ROOT.glob("hub/domains/*/*/interface/api*.py")
    )
    assert found
    return found


@pytest.mark.parametrize("path", domain_routes(), ids=lambda p: str(p.relative_to(ROOT)))
def test_a_domain_route_never_writes(path: Path) -> None:
    source = path.read_text()
    hits = [m.group(0) for pattern in WRITES for m in pattern.finditer(source)]
    assert hits == [], f"{path.relative_to(ROOT)} écrit hors du Double Sas : {hits}"


def test_a_read_does_not_refresh_in_the_request() -> None:
    """`refresh_snapshots()` dans une route GET part en tâche de fond, jamais avant la réponse."""
    for path in domain_routes():
        for line in path.read_text().splitlines():
            if "refresh_snapshots" in line and "def " not in line:
                assert "add_task" in line, f"{path.relative_to(ROOT)} : {line.strip()}"
