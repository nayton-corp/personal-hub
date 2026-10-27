import threading
from pathlib import Path

import pytest
from sqlalchemy import event, text

from hub.core.db import DatabaseBusy, backup, begin_immediate, integrity_check, make_engine


def test_pragmas_on_every_connection(tmp_path: Path) -> None:
    engine = make_engine(tmp_path / "a" / "x.db")
    with engine.connect() as conn:
        assert conn.execute(text("PRAGMA journal_mode")).scalar() == "wal"
        assert conn.execute(text("PRAGMA foreign_keys")).scalar() == 1
        assert conn.execute(text("PRAGMA recursive_triggers")).scalar() == 1
        assert conn.execute(text("PRAGMA busy_timeout")).scalar() == 5000
        assert conn.execute(text("PRAGMA synchronous")).scalar() == 1
    engine.dispose()


def test_begin_immediate_takes_write_lock(tmp_path: Path) -> None:
    path = tmp_path / "x.db"
    engine = make_engine(path)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE t (v INTEGER)"))
    other = make_engine(path)

    @event.listens_for(other, "connect")
    def _short_timeout(dbapi_conn, _record):  # type: ignore[no-untyped-def]
        dbapi_conn.execute("PRAGMA busy_timeout=50")

    entered = threading.Event()
    release = threading.Event()

    def hold() -> None:
        with begin_immediate(engine) as conn:
            conn.execute(text("INSERT INTO t VALUES (1)"))
            entered.set()
            release.wait(5)

    t = threading.Thread(target=hold)
    t.start()
    entered.wait(5)
    try:
        with pytest.raises(DatabaseBusy), begin_immediate(other):
            pass
    finally:
        release.set()
        t.join()
    with begin_immediate(other) as conn:
        assert conn.execute(text("SELECT count(*) FROM t")).scalar() == 1
    engine.dispose()
    other.dispose()


def test_backup_is_consistent(tmp_path: Path) -> None:
    engine = make_engine(tmp_path / "x.db")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE t (v INTEGER)"))
        conn.execute(text("INSERT INTO t VALUES (42)"))
    target = tmp_path / "backup" / "x-copy.db"
    backup(engine, target)
    assert integrity_check(target) == "ok"
    copy = make_engine(target)
    with copy.connect() as conn:
        assert conn.execute(text("SELECT v FROM t")).scalar() == 42
    engine.dispose()
    copy.dispose()
