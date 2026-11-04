"""Les scripts de `scripts/` (hors du paquet `hub`), chargés par leur fichier pour les tester."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[2]


def load_script(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # les dataclasses relisent leur module par son nom
    spec.loader.exec_module(module)
    return module
