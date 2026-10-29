"""Accès à `core.db` : moteur, migration et journal d'audit."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import Connection, Engine, text

from hub.kernel.clock import now_iso
from hub.platform import migrations as runner
from hub.platform.db import make_engine
from hub.platform.settings import Settings

CORE_SCRIPT_LOCATION = Path(__file__).parent / "migrations"


class CoreDB:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.engine: Engine = make_engine(path)

    @classmethod
    def from_settings(cls, settings: Settings) -> CoreDB:
        return cls(settings.db_path("core"))

    def migrate(self) -> None:
        runner.upgrade(CORE_SCRIPT_LOCATION, self.path)

    def revision(self) -> str | None:
        return runner.current(CORE_SCRIPT_LOCATION, self.path)

    def is_current(self) -> bool:
        return self.revision() == runner.head(CORE_SCRIPT_LOCATION)

    def dispose(self) -> None:
        self.engine.dispose()


def audit(conn: Connection, actor: str, action: str, target: str | None, outcome: str) -> None:
    """Trace en ajout seul. `target` ne contient que des identifiants."""
    conn.execute(
        text(
            "INSERT INTO audit (at, actor, action, target, outcome) "
            "VALUES (:at, :actor, :action, :target, :outcome)"
        ),
        {"at": now_iso(), "actor": actor, "action": action, "target": target, "outcome": outcome},
    )
