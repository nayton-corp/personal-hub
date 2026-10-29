"""Les liens relatifs de la documentation mènent à un fichier qui existe (chantier S14) : un
document déplacé sans ses liens fait échouer la CI."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LINK = re.compile(r"\]\(([^)#\s]+)(?:#[^)]*)?\)")


def _documents() -> list[Path]:
    found = [ROOT / "README.md", ROOT / "vision.md", ROOT / "CONTRIBUTING.md"]
    found += sorted((ROOT / "docs").rglob("*.md")) + sorted((ROOT / "hub").rglob("README.md"))
    return [p for p in found if p.exists()]


def test_relative_links_resolve() -> None:
    broken = []
    for doc in _documents():
        for target in LINK.findall(doc.read_text()):
            if re.match(r"^[a-z]+:", target):
                continue  # https:, mailto:
            if not (doc.parent / target).exists():
                broken.append(f"{doc.relative_to(ROOT)} → {target}")
    assert broken == []
