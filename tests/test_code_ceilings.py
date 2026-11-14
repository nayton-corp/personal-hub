"""Plafonds qui ne peuvent que baisser (audit du 10/11, Q1 et Q2), comme la liste des fichiers
trop longs : la dette d'aujourd'hui est comptée, elle ne grossit plus.

- les `Any` de hub/ : un contrat interne non vérifié de plus se voit en revue ;
- les lignes de plus de 200 caractères de l'app : la règle des 400 lignes ne se tient pas en
  écrivant des lignes de plusieurs centaines de caractères.

Un compteur qui baisse franchement abaisse son plafond : la marge gagnée n'est pas reprise.
"""

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
ANY = re.compile(r"\bAny\b")
WIDE = 200
SLACK = 10  # on ne retouche pas le plafond pour une ligne de moins

CEILINGS = {"any": 955, "wide_lines": 269}


def _any() -> int:
    return sum(len(ANY.findall(p.read_text())) for p in (REPO / "hub").rglob("*.py"))


def _wide_lines() -> int:
    return sum(
        len(line) > WIDE
        for p in (REPO / "hub").rglob("*.js")
        for line in p.read_text().splitlines()
    )


COUNTS = {"any": _any, "wide_lines": _wide_lines}


@pytest.mark.parametrize("name", sorted(CEILINGS))
def test_the_count_does_not_grow(name: str) -> None:
    assert COUNTS[name]() <= CEILINGS[name], "au-dessus du plafond : typer, ou couper la ligne"


@pytest.mark.parametrize("name", sorted(CEILINGS))
def test_the_ceiling_follows_the_count_down(name: str) -> None:
    assert COUNTS[name]() > CEILINGS[name] - SLACK, "abaisser le plafond au compte actuel"
