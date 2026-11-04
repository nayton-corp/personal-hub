"""Types de l'API pour l'app depuis l'OpenAPI (audit M10, m9) : `hub/web/api.d.ts`.

Chaque schéma de sortie des routes devient une interface ; un module de l'app la nomme en JSDoc
(`/** @type {import("../../web/api").MoneyOut} */`) et `// @ts-check` la vérifie (`make web`).
Généré par `make openapi`, vérifié par `tests/test_api_types.py`.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from hub.api.app import create_app
from hub.core.context import HubContext
from hub.platform.settings import Settings

OUT = Path(__file__).resolve().parents[1] / "hub" / "web" / "api.d.ts"
HEAD = (
    "// Généré par `make openapi` (scripts/jstypes.py) depuis l'OpenAPI : ne pas modifier à la\n"
    "// main. Montants : des MoneyOut (centimes, devise, texte) ; parts et taux : du texte.\n"
)


def js_type(schema: dict[str, Any]) -> str:
    """Le type TypeScript d'un schéma JSON (références, unions, listes, dictionnaires)."""
    if "$ref" in schema:
        return str(schema["$ref"]).rsplit("/", 1)[1]
    if "anyOf" in schema:
        return " | ".join(js_type(x) for x in schema["anyOf"])
    if "enum" in schema:
        return " | ".join(f'"{v}"' if isinstance(v, str) else str(v) for v in schema["enum"])
    kind = schema.get("type")
    if kind == "null":
        return "null"
    if kind == "string":
        return "string"
    if kind in ("integer", "number"):
        return "number"
    if kind == "boolean":
        return "boolean"
    if kind == "array":
        inner = js_type(schema.get("items") or {})
        return f"({inner})[]" if " | " in inner else f"{inner}[]"
    if kind == "object":
        extra = schema.get("additionalProperties")
        if isinstance(extra, dict):
            return f"Record<string, {js_type(extra)}>"
        if schema.get("properties"):
            return "object"
        return "Record<string, any>"
    return "any"


def interface(name: str, schema: dict[str, Any]) -> str:
    required = set(schema.get("required") or [])
    lines = [f"export interface {name} {{"]
    for prop, sub in (schema.get("properties") or {}).items():
        key = prop if prop in required else f"{prop}?"
        lines.append(f"  {key}: {js_type(sub)};")
    return "\n".join([*lines, "}"])


def render_schemas(schemas: dict[str, Any]) -> str:
    body = "\n\n".join(interface(name, schemas[name]) for name in sorted(schemas))
    return f"{HEAD}\n{body}\n"


def render(settings: Settings) -> str:
    hub = HubContext.build(settings)
    hub.migrate_all()
    try:
        schema = create_app(hub).openapi()
    finally:
        hub.dispose()
    return render_schemas(schema.get("components", {}).get("schemas", {}))


if __name__ == "__main__":  # make openapi : écrit hub/web/api.d.ts depuis une instance jetable
    import tempfile

    from hub.platform.settings import Paths

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        paths = Paths(**{k: root / k for k in ("data", "inbox", "archive", "backup")})
        OUT.write_text(render(Settings(paths=paths, domains="*")))
        print(OUT, file=sys.stderr)
