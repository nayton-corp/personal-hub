"""Les références de docs/reference/ suivent le code (chantier S14) : une route, un outil ou un
connecteur ajouté sans `make reference` fait échouer la CI."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

from hub.platform.settings import Settings, get_settings

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("reference", ROOT / "scripts" / "reference.py")
assert _spec
assert _spec.loader
reference = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(reference)


def test_the_generated_references_are_up_to_date(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HUB_DOMAINS", "*")
    get_settings.cache_clear()
    rendered = reference.render(settings.model_copy(update={"domains": "*"}))
    stale = []
    for name, text in rendered.items():
        path = ROOT / "docs" / "reference" / name
        if os.environ.get("UPDATE_REFERENCE") == "1":
            path.write_text(text)
        if not path.exists() or path.read_text() != text:
            stale.append(name)
    assert stale == [], f"référence périmée, lancer `make reference` : {stale}"
