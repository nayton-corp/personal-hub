"""Chantier S3 : le registre d'ajout seul vient du cœur. Un domaine neuf crée ses tables avec
`integrity.schema()`, écrit par `Ledger.append` et se vérifie par `Ledger.verify`."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError

from hub.core import integrity
from hub.core.manifest import unguarded
from hub.domains.finance import hashing
from hub.kernel import chain
from hub.platform.db import begin_immediate, make_engine

FIELDS = {**integrity.COMMON_FIELDS, "notes": {1: ("text",), 2: ("text", "author")}}
LEDGER = integrity.Ledger(FIELDS)


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    engine = make_engine(tmp_path / "x.db")
    with engine.begin() as conn:
        for statement in [
            *integrity.schema(),
            "CREATE TABLE notes (seq INTEGER PRIMARY KEY, text TEXT, author TEXT, hash_v INT)",
            *integrity.append_only("notes"),
        ]:
            conn.execute(text(statement))
    return engine


def test_append_verify_and_the_common_tables(engine: Engine) -> None:
    with begin_immediate(engine) as conn:
        LEDGER.append(conn, "notes", {"text": "a", "author": "n"})
        LEDGER.record_applied(conn, "p1", "add_note", {"seq": 1})
    with engine.connect() as conn:
        result = LEDGER.verify(conn)
        assert result.ok, result.errors
        assert result.links == 3
        assert result.rows == {"applied_proposals": 1, "events": 1, "notes": 1}
        assert integrity.applied(conn, ["p1", "p2"]) == {"p1": {"seq": 1}}
        assert integrity.applied(conn, []) == {}
        (event,) = integrity.events_since(conn, 0, 10)
        assert (event.type, event.urn, event.payload) == (
            "proposal.applied",
            "hub:core:proposal:p1",
            {"kind": "add_note"},
        )
        assert integrity.events_since(conn, event.seq, 10) == []
        assert unguarded(conn, ["notes", "events", "applied_proposals"]) == []


def test_tampering_is_refused_then_detected(engine: Engine) -> None:
    with begin_immediate(engine) as conn:
        LEDGER.append(conn, "notes", {"text": "a", "author": "n"})
    with engine.begin() as conn, pytest.raises(IntegrityError, match="append_only"):
        conn.execute(text("UPDATE notes SET text = 'b'"))
    with engine.begin() as conn:
        conn.execute(text("DROP TRIGGER notes_no_update"))
        conn.execute(text("UPDATE notes SET text = 'b'"))
        conn.execute(text("INSERT INTO notes (text, author, hash_v) VALUES ('c', 'x', 2)"))
    with engine.connect() as conn:
        result = LEDGER.verify(conn)
    assert not result.ok
    assert result.errors == [
        "journal 1 (notes 1) : ligne altérée",
        "notes : 1 ligne(s) hors journal",
    ]


def test_append_refuses_unknown_tables_and_missing_fields(engine: Engine) -> None:
    with begin_immediate(engine) as conn:
        with pytest.raises(integrity.LedgerError, match="non protégée"):
            LEDGER.append(conn, "items", {})
        with pytest.raises(integrity.LedgerError, match="champs absents"):
            LEDGER.append(conn, "notes", {"text": "a"})


def test_versions_hash_their_own_fields() -> None:
    row = {"text": "a", "author": "n"}
    assert chain.row_hash(FIELDS, "notes", row, 1) != chain.row_hash(FIELDS, "notes", row, 2)
    with pytest.raises(ValueError, match="v3"):
        chain.row_hash(FIELDS, "notes", row, 3)


def test_finance_uses_the_common_fields() -> None:
    for table, versions in integrity.COMMON_FIELDS.items():
        assert hashing.FIELDS[table] == versions
