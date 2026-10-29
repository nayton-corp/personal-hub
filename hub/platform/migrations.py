"""Lance les migrations d'une base depuis le code (CLI, déploiement, tests)."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config

from hub.platform.db import make_engine


def url_to_path(url: str) -> Path:
    prefix = "sqlite:///"
    if not url.startswith(prefix):
        raise ValueError("seul SQLite est pris en charge")
    return Path(url[len(prefix) :])


def alembic_config(script_location: Path, db_path: Path) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(script_location))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    return cfg


def upgrade(script_location: Path, db_path: Path, revision: str = "head") -> None:
    command.upgrade(alembic_config(script_location, db_path), revision)


def current(script_location: Path, db_path: Path) -> str | None:
    from alembic.runtime.migration import MigrationContext

    if not db_path.exists():
        return None
    engine = make_engine(db_path)
    try:
        with engine.connect() as conn:
            return MigrationContext.configure(conn).get_current_revision()
    finally:
        engine.dispose()


def head(script_location: Path) -> str | None:
    from alembic.script import ScriptDirectory

    return ScriptDirectory.from_config(
        alembic_config(script_location, Path("x.db"))
    ).get_current_head()
