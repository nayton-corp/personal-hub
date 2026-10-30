"""La recette docs/ajouter-un-domaine.md (chantier S14) couvre tout le contrat de domaine et tout
le manifeste, et le domaine factice la suit : un point du contrat ajouté sans la recette, ou
une recette que le domaine factice ne suit plus, fait échouer la CI."""

from __future__ import annotations

import dataclasses
import re
from pathlib import Path

from hub.core.domain import Domain
from hub.core.manifest import AppModule, Manifest
from tests.support.demo_domain import MANIFEST, DemoDomain

ROOT = Path(__file__).resolve().parents[1]
RECIPE = (ROOT / "docs" / "ajouter-un-domaine.md").read_text()
MODULES = ROOT / "tests" / "web" / "modules"


def _contract() -> set[str]:
    members = set(Domain.__annotations__)
    members |= {n for n, v in vars(Domain).items() if callable(v) and not n.startswith("_")}
    return members


def _cited(name: str) -> bool:
    return re.search(rf"`{name}(\(|`)", RECIPE) is not None


def test_the_recipe_covers_the_whole_contract() -> None:
    missing = sorted(m for m in _contract() if not _cited(m))
    assert missing == [], f"absent de la recette : {missing}"
    fields = {f.name for f in dataclasses.fields(Manifest)} | {
        f.name for f in dataclasses.fields(AppModule)
    }
    assert sorted(f for f in fields if not _cited(f)) == []


def test_the_demo_domain_follows_the_recipe(tmp_path: Path) -> None:
    demo = DemoDomain(tmp_path)
    assert isinstance(demo, Domain)
    assert all(hasattr(demo, m) for m in _contract())
    assert demo.manifest() is MANIFEST
    assert MANIFEST.problems() == []
    assert {s.split(":")[1] for s in demo.scopes} <= {"read", "aggregates", "propose"}
    exports = {
        f.name: set(re.findall(r"^export (?:function|const) (\w+)", f.read_text(), re.M))
        for f in MODULES.glob("*.js")
    }
    tab = exports[MANIFEST.app.tabs[0].module]
    assert {"render", "actions", "todoCount", "todoLabel", "rubric", "rubricStatus", "init"} <= tab
    assert "render" in exports[str(MANIFEST.app.home)]
