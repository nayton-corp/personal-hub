"""Conventions : un journal ne porte ni montant, ni libellé, ni texte venu de l'extérieur.

Le filtre de `hub.core.logging` rejette à l'exécution un événement qui porte une clé interdite.
Ce test le complète à la lecture du code : le nom d'un événement est un texte fixe (jamais une
f-string ni une concaténation), aucune clé interdite n'est écrite, et le texte d'une exception
(`str(exc)`, qui peut reprendre une page ou une réponse d'un tiers) n'est pas journalisé : on
garde `type(exc).__name__`.
"""

import ast
from pathlib import Path

from hub.core.logging import FORBIDDEN_KEYS

ROOT = Path(__file__).resolve().parents[1] / "hub"
LEVELS = frozenset({"debug", "info", "warning", "error", "exception", "critical"})

# écarts d'aujourd'hui (fichier relatif à hub/ → nombre) : la liste ne peut que rétrécir
KNOWN: dict[str, int] = {
    "collectors/runtime.py": 5,
}


def _is_str_of_exception(node: ast.expr) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "str"
        and len(node.args) == 1
        and isinstance(node.args[0], ast.Name)
        and node.args[0].id in {"exc", "e", "err", "error"}
    )


def problems_in(source: str) -> list[str]:
    found = []
    for node in ast.walk(ast.parse(source)):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in LEVELS
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in {"log", "logger"}
        ):
            continue
        if node.args and not isinstance(node.args[0], ast.Constant | ast.Name):
            found.append(f"l.{node.lineno} nom d'événement calculé")
        for kw in node.keywords:
            if kw.arg is not None and kw.arg.lower() in FORBIDDEN_KEYS:
                found.append(f"l.{node.lineno} clé interdite {kw.arg}")
            if _is_str_of_exception(kw.value):
                found.append(f"l.{node.lineno} texte d'exception")
    return found


def _all() -> dict[str, list[str]]:
    out = {str(p.relative_to(ROOT)): problems_in(p.read_text()) for p in ROOT.rglob("*.py")}
    return {k: v for k, v in out.items() if v}


def test_no_new_unsafe_log_call() -> None:
    new = {k: v for k, v in _all().items() if len(v) > KNOWN.get(k, 0)}
    assert new == {}


def test_known_list_only_shrinks() -> None:
    found = _all()
    stale = {k: (len(found.get(k, [])), n) for k, n in KNOWN.items() if len(found.get(k, [])) < n}
    assert stale == {}, "écart corrigé : abaisser ou retirer sa ligne dans KNOWN"


def test_detector() -> None:
    assert problems_in("log.info('x', count=1)") == []
    assert problems_in("log.info(event, **summary)") == []
    assert problems_in("log.info(f'paid {x}')") == ["l.1 nom d'événement calculé"]
    assert problems_in("log.info('x', amount=1)") == ["l.1 clé interdite amount"]
    assert problems_in("log.warning('x', error=str(exc))") == ["l.1 texte d'exception"]
    assert problems_in("log.warning('x', error=type(exc).__name__)") == []
    assert problems_in("log.info('x', question=q)") == ["l.1 clé interdite question"]
