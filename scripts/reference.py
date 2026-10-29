"""Références générées (chantier S14) : routes de l'API, outils de l'assistant, connecteurs.

Elles se tirent du code (OpenAPI de l'application montée avec tous les domaines installés, outils
de chaque domaine, catalogue des connecteurs) ; `tests/test_reference_docs.py` les compare aux
fichiers de `docs/reference/`, et une référence périmée fait échouer la CI. Après un changement
voulu : `make reference`.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from hub.api.app import create_app
from hub.core import connectors
from hub.core.context import HubContext
from hub.platform.settings import Settings

OUT = Path(__file__).resolve().parents[1] / "docs" / "reference"
HEAD = (
    "<!-- Généré par `make reference` (scripts/reference.py) : ne pas modifier à la main. -->\n\n"
)
METHODS = ("get", "post", "put", "patch", "delete")


def _cell(text: str | None) -> str:
    first = (text or "").strip().split("\n\n")[0]
    return " ".join(first.split()).replace("|", "\\|")


def api(hub: HubContext) -> str:
    schema = create_app(hub).openapi()
    rows: dict[str, list[str]] = {}
    for path, ops in sorted(schema["paths"].items()):
        for method in METHODS:
            if method not in ops:
                continue
            part = path.split("/")[2] if path.startswith("/api/") else "autres"
            group = part if part in hub.registry.names() else "cœur"
            doc = ops[method].get("description") or ops[method].get("summary")
            rows.setdefault(group, []).append(f"| `{method.upper()}` | `{path}` | {_cell(doc)} |")
    out = [HEAD, "# Routes de l'API\n\n"]
    out.append(
        "Toutes les routes, cœur puis domaines installés. La portée exigée et les erreurs sont "
        "dans le code ; le contrat complet du cœur est `tests/openapi.snapshot.json`.\n"
    )
    for group in ["cœur", *sorted(g for g in rows if g != "cœur")]:
        out.append(f"\n## {group.capitalize()}\n\n| Méthode | Chemin | Rôle |\n|---|---|---|\n")
        out.append("\n".join(rows.get(group, [])) + "\n")
    return "".join(out)


def tools(hub: HubContext) -> str:
    out = [HEAD, "# Outils de l'assistant\n\n"]
    out.append(
        "Les outils que chaque domaine donne à l'assistant (`hub_capabilities`, puis "
        "`hub_load_tools`). Un outil `…:aggregates` est aussi ouvert à `…:read` ; un outil de "
        "proposition crée une carte à valider dans l'app, jamais un effet.\n"
    )
    for domain in hub.registry:
        out.append(
            f"\n## {domain.name.capitalize()}\n\n| Outil | Portée | Paramètres | Rôle |\n"
            "|---|---|---|---|\n"
        )
        for t in domain.mcp_tools():
            props: dict[str, Any] = t.input_schema.get("properties", {})
            needed = set(t.input_schema.get("required", []))
            params = ", ".join(f"`{p}`" + ("" if p in needed else "?") for p in props) or "—"
            out.append(f"| `{t.name}` | `{t.scope}` | {params} | {_cell(t.description)} |\n")
    return "".join(out)


def connectors_md() -> str:
    out = [HEAD, "# Connecteurs\n\n"]
    out.append(
        "Le catalogue des sources que le hub sait collecter (point d'entrée `hub.connectors`). "
        "Les secrets sont nommés, jamais montrés ; une connexion les donne à sa création.\n\n"
        "| Connecteur | Nom | Domaine | Méthode | Pays | Comptes | Secrets | Réglages | Horaire |\n"
        "|---|---|---|---|---|---|---|---|---|\n"
    )
    for c in sorted(connectors.catalog(), key=lambda c: c.name):

        def ls(xs: tuple[str, ...]) -> str:
            return ", ".join(f"`{x}`" for x in xs) or "—"

        out.append(
            f"| `{c.name}` | {_cell(c.label)} | {c.domain} | {c.method} | {c.country or '—'} | "
            f"{ls(c.accounts)} | {ls(c.secrets)} | {ls(c.settings)} | `{c.schedule}` |\n"
        )
    return "".join(out)


def render(settings: Settings) -> dict[str, str]:
    hub = HubContext.build(settings)
    hub.migrate_all()
    try:
        return {"api.md": api(hub), "outils.md": tools(hub), "connecteurs.md": connectors_md()}
    finally:
        hub.dispose()


if __name__ == "__main__":  # make reference : écrit docs/reference/ depuis une instance jetable
    import tempfile

    from hub.platform.settings import Paths

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        paths = Paths(**{k: root / k for k in ("data", "inbox", "archive", "backup")})
        for name, text in render(Settings(paths=paths)).items():
            (OUT / name).write_text(text)
            print(OUT / name, file=sys.stderr)
