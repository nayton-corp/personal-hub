"""Boîte d'entrée par domaine (chantier S4).

Un fichier déposé à la racine de `inbox/` (à la main, par AirDrop, par un raccourci) est confié
au domaine qui le réclame (`Registry.claimant`, d'après les importeurs du manifeste) : il part
dans `inbox/<domaine>/`, où seul ce domaine le lit. Un fichier que personne ne réclame, ou que
plusieurs réclament, reste à la racine. Les collecteurs déposent directement dans le dossier de
leur domaine.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from hub.core.registry import Registry
from hub.platform.logging import get_logger

HEAD_BYTES = 4096  # le début du fichier, pour qu'un importeur reconnaisse son format
SETTLE_SECONDS = 2  # un fichier modifié il y a moins longtemps est peut-être encore en copie
log = get_logger("hub.inbox")


@dataclass
class Routed:
    moved: dict[str, int] = field(default_factory=dict)  # domaine → fichiers rangés
    waiting: int = 0  # réclamés par personne (ou par plusieurs)

    def public(self) -> dict[str, object]:
        return {"moved": self.moved, "waiting": self.waiting}


def _free(target: Path) -> Path:
    """Un nom libre dans le dossier du domaine : `x.pdf`, puis `x-2.pdf`, `x-3.pdf`…"""
    candidate, n = target, 1
    while candidate.exists():
        n += 1
        candidate = target.with_name(f"{target.stem}-{n}{target.suffix}")
    return candidate


def route(registry: Registry, root: Path, *, settle: int = SETTLE_SECONDS) -> Routed:
    """Range les fichiers prêts de la racine ; les dossiers (domaines, quarantaine) restent."""
    out = Routed()
    if not root.is_dir():
        return out
    now = time.time()
    for path in sorted(root.iterdir()):
        if not path.is_file() or path.name.startswith("."):
            continue
        if now - path.stat().st_mtime < settle:
            continue
        with path.open("rb") as f:
            head = f.read(HEAD_BYTES)
        domain = registry.claimant(path.name, head)
        if domain is None:
            out.waiting += 1
            continue
        folder = root / domain
        folder.mkdir(parents=True, exist_ok=True)
        path.replace(_free(folder / path.name))
        out.moved[domain] = out.moved.get(domain, 0) + 1
    if out.moved or out.waiting:
        log.info("inbox.routed", waiting=out.waiting, **out.moved)
    return out


def adopt(root: Path, domain: str, owns: Callable[[str], bool]) -> int:
    """Déplacement unique d'avant S4 : les entrées de `root` que `owns(nom)` reconnaît passent
    dans `root/<domaine>/`. Sans danger à relancer (le dossier du domaine n'est jamais repris)."""
    if not root.is_dir():
        return 0
    moved = 0
    for path in sorted(root.iterdir()):
        if path.name == domain or not owns(path.name):
            continue
        target = root / domain / path.name
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            log.warning("inbox.adopt_conflict", domain=domain)
            continue
        path.replace(target)
        moved += 1
    if moved:
        log.info("inbox.adopted", domain=domain, entries=moved)
    return moved
