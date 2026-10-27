"""Domaine Finance : registre BCF, import camt.053 (lot 1) et lectures de l'app (lot 2)."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import typer
from fastapi import APIRouter
from sqlalchemy import Engine, text

from hub.core.clock import utcnow
from hub.core.db import make_engine
from hub.core.domain import Event, Health, Hit, McpTool, ProposalKind, Ref
from hub.core.ids import Urn, urn
from hub.core.logging import get_logger
from hub.core.migrations import runner
from hub.core.settings import Settings
from hub.domains.finance import ledger, reads, snapshots
from hub.domains.finance.importer import Archiver, ImportService, recipient_from_key

MIGRATIONS = Path(__file__).parent / "migrations"
SCHEMA_VERSION = 3  # 0003_snapshots
TZ = ZoneInfo("Europe/Zurich")  # le jour civil des chiffres de l'app
log = get_logger("hub.finance")


class FinanceDomain:
    name = "finance"
    schema_version = SCHEMA_VERSION
    scopes = frozenset({"finance:read", "finance:propose", "finance:aggregates"})
    # les types de proposition (Double Sas) arrivent au lot 3
    proposal_kinds: Mapping[str, ProposalKind] = {}

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.path = settings.db_path("finance")
        self._engine = make_engine(self.path)
        section = settings.domain("finance")
        key_file = settings.secrets.age_key_file
        recipient = section.get("archive_recipient") or recipient_from_key(key_file)
        self.importer = ImportService(
            self._engine,
            inbox=settings.paths.inbox,
            archiver=Archiver(settings.paths.archive, recipient, key_file),
            lock_file=settings.paths.data / "finance.history.lock",
            on_applied=self.refresh_snapshots,
        )
        cap = section.get("pillar3a_cap_minor")
        self.pillar3a_cap: int | None = int(cap) if cap is not None else None

    def engine(self) -> Engine:
        return self._engine

    def migrate(self) -> None:
        runner.upgrade(MIGRATIONS, self.path)

    def is_current(self) -> bool:
        return runner.current(MIGRATIONS, self.path) == runner.head(MIGRATIONS)

    def router(self) -> APIRouter:
        from hub.domains.finance.api import build_router

        return build_router(self)

    def cli(self) -> typer.Typer | None:
        from hub.domains.finance.cli import build_cli

        return build_cli(self)

    def mcp_tools(self) -> list[McpTool]:
        return []  # les 15 outils MCP arrivent avec la passerelle

    def search(self, q: str, limit: int, scopes: frozenset[str]) -> list[Hit]:
        with self._engine.connect() as conn:
            found = reads.search(conn, q, limit)
        hits = []
        for rank, e in enumerate(found):
            title = e["counterparty"] or e["label"] or "écriture"
            hits.append(
                Hit(urn("finance", "entry", e["id"]), title, e["booking_date"], len(found) - rank)
            )
        return hits

    def resolve(self, value: str) -> Ref | None:
        u = Urn.parse(value)
        with self._engine.connect() as conn:
            if u.type == "entry":
                row = conn.execute(
                    text("SELECT counterparty, label, booking_date FROM entries WHERE id = :i"),
                    {"i": u.id},
                ).first()
                if row:
                    return Ref(
                        value, row[0] or row[1] or "écriture", row[2], f"/finance/entries/{u.id}"
                    )
            elif u.type == "account":
                row = conn.execute(
                    text("SELECT name FROM accounts WHERE id = :i"), {"i": u.id}
                ).first()
                if row:
                    return Ref(value, row[0], None, f"/finance/accounts/{u.id}")
            elif u.type == "import":
                row = conn.execute(
                    text("SELECT file_name, received_at FROM imports WHERE id = :i"), {"i": u.id}
                ).first()
                if row:
                    return Ref(value, row[0], row[1][:10], f"/finance/imports/{u.id}")
        return None

    def events_since(self, cursor: int, limit: int) -> list[Event]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT seq, type, urn, payload_json, created_at FROM events WHERE seq > :c "
                    "ORDER BY seq LIMIT :n"
                ),
                {"c": cursor, "n": limit},
            ).fetchall()
        return [Event(r[0], r[1], r[2], json.loads(r[3]), r[4]) for r in rows]

    def applied(self, proposal_ids: Sequence[str]) -> Mapping[str, dict[str, Any]]:
        if not proposal_ids:
            return {}
        marks = ",".join(f":p{i}" for i in range(len(proposal_ids)))
        with self._engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT proposal_id, result_json FROM applied_proposals "
                    f"WHERE proposal_id IN ({marks})"
                ),
                {f"p{i}": p for i, p in enumerate(proposal_ids)},
            ).fetchall()
        return {pid: json.loads(res) for pid, res in rows}

    def verify_ledger(self) -> ledger.VerifyResult:
        with self._engine.connect() as conn:
            return ledger.verify(conn)

    def today(self) -> date:
        """Date civile à Zurich : fixe « aujourd'hui » pour les chiffres de l'app."""
        return utcnow().astimezone(TZ).date()

    def refresh_snapshots(self, *, force: bool = False) -> snapshots.Refresh:
        return snapshots.refresh(self._engine, self.today(), force=force)

    def nightly(self) -> None:
        refreshed = self.refresh_snapshots(force=True)
        log.info("snapshots.nightly", rows=refreshed.rows)
        result = self.verify_ledger()
        if result.ok:
            log.info("ledger.verified", links=result.links)
        else:
            log.error("ledger.verify_failed", errors=result.errors[:5])

    def health(self) -> Health:
        if not self.path.exists():
            return Health(ok=False, db="missing", schema_version=self.schema_version)
        try:
            current = self.is_current()
        except Exception:
            return Health(ok=False, db="error", schema_version=self.schema_version)
        return Health(
            ok=current, db="ok" if current else "outdated", schema_version=self.schema_version
        )

    def verify(self) -> Health:
        health = self.health()
        if not health.ok:
            return health
        result = self.verify_ledger()
        return Health(
            ok=result.ok,
            db=health.db,
            schema_version=self.schema_version,
            detail={"ledger": result.public()},
        )


def create(settings: Settings) -> FinanceDomain:
    """Point d'entrée `hub.domains` (pyproject.toml)."""
    return FinanceDomain(settings)
