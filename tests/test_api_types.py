"""Les types de l'API pour l'app (`hub/web/api.d.ts`) suivent l'OpenAPI (audit M10, m9) : un
schéma de sortie changé sans `make openapi` fait échouer la CI."""

import importlib.util
import os
from pathlib import Path

import pytest

from hub.platform.settings import Settings, get_settings

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("jstypes", ROOT / "scripts" / "jstypes.py")
assert _spec is not None
assert _spec.loader is not None
jstypes = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(jstypes)


def test_js_types_follow_the_schemas() -> None:
    rendered = jstypes.render_schemas(
        {
            "MoneyOut": {
                "type": "object",
                "required": ["minor", "currency"],
                "properties": {
                    "minor": {"type": "integer"},
                    "currency": {"type": "string"},
                    "note": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "by_key": {"type": "object", "additionalProperties": {"$ref": "#/x/Row"}},
                    "raw": {"type": "object"},
                },
            }
        }
    )
    assert "export interface MoneyOut {" in rendered
    assert "  minor: number;" in rendered
    assert "  note?: string | null;" in rendered
    assert "  tags?: string[];" in rendered
    assert "  by_key?: Record<string, Row>;" in rendered
    assert "  raw?: Record<string, any>;" in rendered


def test_the_generated_types_are_up_to_date(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HUB_DOMAINS", "*")
    get_settings.cache_clear()
    rendered = jstypes.render(settings.model_copy(update={"domains": "*"}))
    path = ROOT / "hub" / "web" / "api.d.ts"
    if os.environ.get("UPDATE_OPENAPI") == "1":
        path.write_text(rendered)
    assert path.exists(), "types absents : lancer `make openapi`"
    assert path.read_text() == rendered, "types périmés : lancer `make openapi`"
