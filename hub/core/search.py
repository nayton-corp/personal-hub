"""Recherche commune (chantier S9) : fusion des résultats des domaines par rang.

Chaque domaine classe ses résultats à sa façon (bm25 pour la finance, ordre d'insertion pour
un autre) ; ces scores ne se comparent pas d'un domaine à l'autre. La fusion ne garde que le
rang de chaque résultat dans son domaine (Reciprocal Rank Fusion, k = 60), en entiers : le
premier de chaque domaine passe avant le second de tous, quel que soit le score brut.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from hub.core.domain import Hit

K = 60
SCALE = 1_000_000


@dataclass(frozen=True)
class Found:
    domain: str  # la provenance
    rank: int  # rang dans son domaine, à partir de 1
    score: int  # score fusionné, entier
    hit: Hit


def fuse(per_domain: Mapping[str, Sequence[Hit]], limit: int) -> list[Found]:
    found: list[Found] = []
    for domain, hits in per_domain.items():
        ordered = sorted(hits, key=lambda h: h.score, reverse=True)  # tri stable
        found.extend(
            Found(domain, rank, SCALE // (K + rank), hit)
            for rank, hit in enumerate(ordered, start=1)
        )
    # à rang égal : le plus récent (sans date en dernier), puis le domaine ; tris stables
    found.sort(key=lambda f: (f.domain, f.hit.urn))
    found.sort(key=lambda f: f.hit.date or "", reverse=True)
    found.sort(key=lambda f: f.score, reverse=True)
    return found[:limit]


def excerpt(texts: Sequence[str | None], q: str, width: int = 80) -> str | None:
    """Le passage du premier texte qui contient la requête, recentré sur elle et coupé à
    `width` caractères ; à défaut, le début du premier texte non vide."""
    present = [" ".join(t.split()) for t in texts if t and t.strip()]
    if not present:
        return None
    needle = q.casefold().strip()
    for t in present:
        at = t.casefold().find(needle)
        if at >= 0:
            start = max(0, min(at - width // 3, len(t) - width))
            return _cut(t, start, width)
    return _cut(present[0], 0, width)


def _cut(t: str, start: int, width: int) -> str:
    part = t[start : start + width]
    return ("…" if start > 0 else "") + part + ("…" if start + width < len(t) else "")
