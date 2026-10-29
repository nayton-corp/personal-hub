"""Connexions SQLite : pragmas à chaque connexion et transactions `BEGIN IMMEDIATE`."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import Connection, Engine, create_engine, event
from sqlalchemy.exc import OperationalError

PRAGMAS = (
    "PRAGMA journal_mode=WAL",
    "PRAGMA foreign_keys=ON",
    "PRAGMA busy_timeout=5000",
    "PRAGMA synchronous=NORMAL",
    # sans lui, INSERT OR REPLACE supprime la ligne en conflit sans lancer le
    # déclencheur anti-DELETE
    "PRAGMA recursive_triggers=ON",
)

APPEND_ONLY = "ledger.append_only"


class DatabaseBusy(RuntimeError):
    pass


def make_engine(path: Path) -> Engine:
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite+pysqlite:///{path}", future=True)

    @event.listens_for(engine, "connect")
    def _connect(dbapi_conn: sqlite3.Connection, _record: Any) -> None:
        # on pilote nous-mêmes BEGIN pour pouvoir choisir IMMEDIATE
        dbapi_conn.isolation_level = None
        cur = dbapi_conn.cursor()
        for pragma in PRAGMAS:
            cur.execute(pragma)
        cur.close()

    @event.listens_for(engine, "begin")
    def _begin(conn: Connection) -> None:
        mode = "BEGIN IMMEDIATE" if conn.get_execution_options().get("immediate") else "BEGIN"
        conn.exec_driver_sql(mode)

    return engine


@contextmanager
def begin_immediate(engine: Engine) -> Iterator[Connection]:
    """Prend le verrou d'écriture dès l'ouverture : ce qui est lu ensuite ne change plus."""
    try:
        with engine.connect().execution_options(immediate=True) as conn, conn.begin():
            yield conn
    except OperationalError as exc:
        if "database is locked" in str(exc) or "database is busy" in str(exc):
            raise DatabaseBusy from exc
        raise


def is_append_only_violation(exc: BaseException) -> bool:
    return APPEND_ONLY in str(exc)


def backup(engine: Engine, target: Path) -> None:
    """Copie cohérente, même en WAL (équivalent de `.backup`)."""
    target.parent.mkdir(parents=True, exist_ok=True)
    raw = engine.raw_connection()
    try:
        src = raw.driver_connection
        if not isinstance(src, sqlite3.Connection):
            raise TypeError("connexion SQLite attendue")
        dst = sqlite3.connect(target)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        raw.close()


def integrity_check(path: Path) -> str:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        row = conn.execute("PRAGMA integrity_check").fetchone()
        return str(row[0])
    finally:
        conn.close()
