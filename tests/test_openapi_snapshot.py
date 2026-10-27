"""Contrat : le schéma OpenAPI du cœur est comparé à l'instantané versionné.

Un changement voulu se valide explicitement : `UPDATE_OPENAPI=1 uv run pytest
tests/test_openapi_snapshot.py`, puis on relit le diff de `tests/openapi.snapshot.json`.
"""

import json
import os
from pathlib import Path

from hub.api.app import create_app
from hub.core.context import HubContext
from hub.core.registry import Registry
from hub.core.settings import Settings

SNAPSHOT = Path(__file__).parent / "openapi.snapshot.json"


def test_openapi_matches_snapshot(settings: Settings) -> None:
    hub = HubContext.build(settings, Registry())  # le cœur seul, sans domaine
    schema = create_app(hub).openapi()
    rendered = json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if os.environ.get("UPDATE_OPENAPI") == "1":
        SNAPSHOT.write_text(rendered)
    assert SNAPSHOT.read_text() == rendered, "contrat d'API modifié : voir l'en-tête du test"
    hub.dispose()
