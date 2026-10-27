"""Domaine factice monté par les tests : il doit apparaître dans l'API, la recherche, la santé
et la tâche de nuit sans qu'une ligne du cœur change."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import typer
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection, Engine, text

from hub.core import canonical
from hub.core.auth import require
from hub.core.clock import now_iso
from hub.core.db import make_engine
from hub.core.domain import (
    Event,
    ExternalResult,
    Health,
    Hit,
    McpTool,
    Preview,
    ProposalKind,
    Ref,
)
from hub.core.ids import urn

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (seq INTEGER PRIMARY KEY, name TEXT NOT NULL, created_at TEXT);
CREATE TABLE IF NOT EXISTS applied_proposals (
  proposal_id TEXT PRIMARY KEY, kind TEXT NOT NULL, result_json TEXT NOT NULL,
  applied_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY, type TEXT NOT NULL,
  urn TEXT NOT NULL, payload_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL);
"""


class AddItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=50)


class AddItemHandler:
    def preview(self, conn: Connection, params: BaseModel) -> Preview:
        assert isinstance(params, AddItem)
        n = conn.execute(text("SELECT count(*) FROM items")).scalar_one()
        return Preview(
            summary=f"ajouter {params.name}",
            details={"count_before": n},
            fingerprint=hashlib.sha256(f"items:{n}".encode()).hexdigest(),
        )

    def apply(self, conn: Connection, params: BaseModel, proposal_id: str) -> dict[str, Any]:
        assert isinstance(params, AddItem)
        seq = conn.execute(
            text("INSERT INTO items (name, created_at) VALUES (:n, :at) RETURNING seq"),
            {"n": params.name, "at": now_iso()},
        ).scalar_one()
        return {"seq": seq}


class FakeThirdParty:
    def __init__(self) -> None:
        self.calls: dict[str, str] = {}

    def preview(self, params: BaseModel) -> Preview:
        return Preview(summary="appel externe", details={}, fingerprint="0" * 64)

    def apply(self, params: BaseModel, idempotency_key: str) -> ExternalResult:
        self.calls.setdefault(idempotency_key, "done")
        return ExternalResult("ok", {"calls": len(self.calls)})

    def reconcile(self, proposal_id: str) -> ExternalResult:
        return ExternalResult("ok")


class DemoDomain:
    name = "demo"
    schema_version = 1
    scopes = frozenset({"demo:read", "demo:propose", "demo:aggregates"})

    def __init__(self, data_dir: Path) -> None:
        self.path = data_dir / "demo.db"
        self._engine = make_engine(self.path)
        self.nightly_runs = 0
        self.third_party = FakeThirdParty()
        self.proposal_kinds: Mapping[str, ProposalKind] = {
            "add_item": ProposalKind(
                params_model=AddItem, handler=AddItemHandler(), ai_allowed=True
            ),
            "add_item_human_only": ProposalKind(params_model=AddItem, handler=AddItemHandler()),
            "notify": ProposalKind(params_model=AddItem, handler=self.third_party, external=True),
        }

    def engine(self) -> Engine:
        return self._engine

    def migrate(self) -> None:
        raw = self._engine.raw_connection()
        try:
            raw.driver_connection.executescript(SCHEMA)  # type: ignore[union-attr]
        finally:
            raw.close()

    def router(self) -> APIRouter:
        r = APIRouter()

        @r.get("/items", dependencies=[Depends(require("app", "demo:read"))])
        def items() -> dict[str, Any]:
            with self._engine.connect() as conn:
                rows = conn.execute(text("SELECT seq, name FROM items ORDER BY seq")).fetchall()
            return {"items": [{"seq": s, "name": n} for s, n in rows]}

        @r.get("/summary", dependencies=[Depends(require("app", "demo:read", "demo:aggregates"))])
        def summary() -> dict[str, int]:
            with self._engine.connect() as conn:
                return {"count": conn.execute(text("SELECT count(*) FROM items")).scalar_one()}

        return r

    def cli(self) -> typer.Typer | None:
        return None

    def mcp_tools(self) -> list[McpTool]:
        return [
            McpTool(
                "demo_count", "Nombre d'éléments", {"type": "object"}, "demo:read", lambda _args: 0
            )
        ]

    def search(self, q: str, limit: int, scopes: frozenset[str]) -> list[Hit]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                text("SELECT seq, name, created_at FROM items WHERE name LIKE :q LIMIT :n"),
                {"q": f"%{q}%", "n": limit},
            ).fetchall()
        return [Hit(urn("demo", "item", str(s)), n, at[:10], 10) for s, n, at in rows]

    def resolve(self, value: str) -> Ref | None:
        seq = value.rsplit(":", 1)[1]
        with self._engine.connect() as conn:
            row = conn.execute(text("SELECT name FROM items WHERE seq = :s"), {"s": seq}).first()
        return Ref(value, row[0], None, f"/demo/items/{seq}") if row else None

    def events_since(self, cursor: int, limit: int) -> list[Event]:
        return []

    def applied(self, proposal_ids: Sequence[str]) -> Mapping[str, dict[str, Any]]:
        import json

        if not proposal_ids:
            return {}
        marks = ",".join(f":p{i}" for i in range(len(proposal_ids)))
        with self._engine.connect() as conn:
            rows = conn.execute(
                text(
                    f"SELECT proposal_id, result_json FROM applied_proposals "
                    f"WHERE proposal_id IN ({marks})"
                ),
                {f"p{i}": p for i, p in enumerate(proposal_ids)},
            ).fetchall()
        return {pid: json.loads(res) for pid, res in rows}

    def record_applied(
        self, conn: Connection, proposal_id: str, kind: str, result: dict[str, Any]
    ) -> None:
        conn.execute(
            text("INSERT INTO applied_proposals VALUES (:p, :k, :r, :at)"),
            {"p": proposal_id, "k": kind, "r": canonical.dumps(result), "at": now_iso()},
        )

    def mark_applied(self, proposal_id: str, result: dict[str, Any]) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                text("INSERT INTO applied_proposals VALUES (:p, 'add_item', :r, :at)"),
                {"p": proposal_id, "r": canonical.dumps(result), "at": now_iso()},
            )

    def nightly(self) -> None:
        self.nightly_runs += 1

    def verify(self) -> Health:
        return self.health()

    def health(self) -> Health:
        return Health(
            ok=self.path.exists(),
            db="ok" if self.path.exists() else "missing",
            schema_version=self.schema_version,
        )
