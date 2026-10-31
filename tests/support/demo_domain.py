"""Domaine factice monté par les tests : il doit apparaître dans l'API, la recherche, la santé,
la tâche de nuit, l'app (onglet, carte d'accueil, rubrique), la boîte d'entrée, les constats et
l'assistant sans qu'une ligne du cœur change. Son manifeste remplit chaque champ du contrat."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import typer
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection, Engine, text

from hub.core import integrity
from hub.core.auth import require
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
from hub.core.manifest import (
    AppModule,
    HomeCard,
    Importer,
    Manifest,
    Observation,
    SettingsSection,
    Tab,
)
from hub.core.search import excerpt
from hub.kernel.clock import now_iso
from hub.kernel.ids import urn
from hub.platform.db import make_engine

# journal, applied_proposals et events viennent du cœur (chantier S3) ; items n'est pas chaîné
SCHEMA = [
    "CREATE TABLE items (seq INTEGER PRIMARY KEY, name TEXT NOT NULL, created_at TEXT)",
    *integrity.schema(),
]
LEDGER = integrity.Ledger(integrity.COMMON_FIELDS)

MANIFEST = Manifest(
    description="Domaine factice des tests : des éléments nommés.",
    app=AppModule(
        label="Démo",
        icon="cube",
        tabs=(Tab("demo", "Démo", "list", "demo.js", order=60),),
        home_cards=(HomeCard("compte", "Éléments", "/summary"),),
        settings=(SettingsSection("demo-prefs", "Démo", "gear", "Préférences", "demo.js"),),
        cards="demo.js",
        home="demo-home.js",
        module="demo.js",
        web=Path(__file__).parents[1] / "web" / "modules",
    ),
    importers=(
        Importer(
            "notes",
            "Notes de démo",
            frozenset({".demo", ".txt"}),
            claims=lambda name, head: not name.endswith(".txt") or head.startswith(b"DEMO"),
        ),
    ),
    protected_tables=frozenset({"events", "applied_proposals"}),
    assistant="Ne jamais citer un élément sans son numéro.",
)


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
    description = MANIFEST.description
    schema_version = 1
    scopes = frozenset({"demo:read", "demo:propose", "demo:aggregates"})

    def __init__(self, data_dir: Path, inbox: Path | None = None) -> None:
        self.path = data_dir / f"{self.name}.db"
        self.inbox = inbox or data_dir.parent / "inbox" / self.name
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

    def manifest(self) -> Manifest:
        return MANIFEST

    def process_inbox(self) -> dict[str, int]:
        """Chaque fichier de son dossier devient un élément, puis s'efface."""
        files = (
            sorted(p for p in self.inbox.glob("*") if p.is_file()) if self.inbox.is_dir() else []
        )
        with self._engine.begin() as conn:
            for p in files:
                conn.execute(
                    text("INSERT INTO items (name, created_at) VALUES (:n, :at)"),
                    {"n": p.name, "at": now_iso()},
                )
                p.unlink()
        return {"files": len(files)}

    def observations(self, limit: int) -> list[Observation]:
        with self._engine.connect() as conn:
            n = conn.execute(text("SELECT count(*) FROM items")).scalar_one()
        found = [Observation("demo-empty", "empty", "info", "Aucun élément", "2026-10-29")]
        return found[:limit] if n == 0 else []

    def engine(self) -> Engine:
        return self._engine

    def migrate(self) -> None:
        with self._engine.begin() as conn:
            if conn.execute(text("SELECT 1 FROM sqlite_master WHERE name = 'journal'")).first():
                return
            for statement in SCHEMA:
                conn.execute(text(statement))

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
                "demo_count",
                "Nombre d'éléments",
                {"type": "object"},
                "demo:read",
                lambda _args, _caller: 0,
            )
        ]

    def search(self, q: str, limit: int, scopes: frozenset[str]) -> list[Hit]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                text("SELECT seq, name, created_at FROM items WHERE name LIKE :q LIMIT :n"),
                {"q": f"%{q}%", "n": limit},
            ).fetchall()
        # comme bm25 : le plus court d'abord, sur une échelle à lui (S9 fusionne par rang)
        return [
            Hit(urn(self.name, "item", str(s)), n, at[:10], 1000 - len(n), excerpt([n], q))
            for s, n, at in rows
        ]

    def resolve(self, value: str) -> Ref | None:
        seq = value.rsplit(":", 1)[1]
        with self._engine.connect() as conn:
            row = conn.execute(text("SELECT name FROM items WHERE seq = :s"), {"s": seq}).first()
        return Ref(value, row[0], None, f"/{self.name}/items/{seq}") if row else None

    def events_since(self, cursor: int, limit: int) -> list[Event]:
        with self._engine.connect() as conn:
            return integrity.events_since(conn, cursor, limit)

    def applied(self, proposal_ids: Sequence[str]) -> Mapping[str, dict[str, Any]]:
        with self._engine.connect() as conn:
            return integrity.applied(conn, proposal_ids)

    def record_applied(
        self, conn: Connection, proposal_id: str, kind: str, result: dict[str, Any]
    ) -> None:
        LEDGER.record_applied(conn, proposal_id, kind, result)

    def mark_applied(self, proposal_id: str, result: dict[str, Any]) -> None:
        with self._engine.begin() as conn:
            LEDGER.record_applied(conn, proposal_id, "add_item", result)

    def nightly(self) -> None:
        self.nightly_runs += 1

    def verify(self) -> Health:
        """Le registre commun du cœur : journal, applied_proposals, events."""
        health = self.health()
        if not health.ok:
            return health
        with self._engine.connect() as conn:
            result = LEDGER.verify(conn)
        return Health(result.ok, health.db, self.schema_version, {"ledger": result.public()})

    def health(self) -> Health:
        return Health(
            ok=self.path.exists(),
            db="ok" if self.path.exists() else "missing",
            schema_version=self.schema_version,
        )
