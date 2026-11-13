"""Ce que tous les modules de tests d'écran partagent."""

from __future__ import annotations

from collections.abc import Callable

import pytest


@pytest.fixture(scope="module")
def instance_extra() -> Callable[[dict[str, str]], None]:
    """Ce qu'un module ajoute à l'instance fictive avant que l'app ne tourne : rien, par défaut."""
    return lambda _env: None
