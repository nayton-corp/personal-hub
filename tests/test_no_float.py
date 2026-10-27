"""Conventions : aucun flottant dans hub/ (ruff ne sait pas bannir un builtin)."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "hub"


def floats_in(source: str) -> list[int]:
    lines = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Name) and node.id == "float":
            lines.append(node.lineno)
        if isinstance(node, ast.Constant) and isinstance(node.value, float):
            lines.append(node.lineno)
    return lines


def test_no_float_in_hub() -> None:
    offenders = {str(p.relative_to(ROOT)): floats_in(p.read_text()) for p in ROOT.rglob("*.py")}
    assert {k: v for k, v in offenders.items() if v} == {}


def test_detector() -> None:
    assert floats_in("x = float('1')") == [1]
    assert floats_in("def f(a: float) -> None: ...") == [1]
    assert floats_in("y = 0.5") == [1]
    assert floats_in("z = 1") == []
