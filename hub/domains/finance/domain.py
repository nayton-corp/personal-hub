"""Domaine Finance : registre BCF, import camt.053 (lot 1), lectures de l'app (lot 2),
règles de catégorisation et propositions du Double Sas (lot 3), outils de l'assistant et
sentinelles (lot 7)."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any

import typer
from fastapi import APIRouter
from sqlalchemy import Connection, Engine, event, text

from hub.core import integrity, profile
from hub.core.domain import Event, Health, Hit, McpTool, ProposalKind, Ref
from hub.core.manifest import Manifest, Observation, Severity
from hub.domains.finance import (
    importer,
    ledger,
    manifest,
    packs,
    period,
    reads,
    recurring,
    sentinels,
    snapshots,
    transfers,
)
from hub.domains.finance.handlers import build_kinds
from hub.domains.finance.importer import Archiver, ImportService, recipient_from_key
from hub.kernel.clock import local_today
from hub.kernel.ids import Urn, urn
from hub.kernel.money import base_currency
from hub.platform import migrations as runner
from hub.platform.db import begin_immediate, make_engine
from hub.platform.logging import get_logger
from hub.platform.settings import Settings

MIGRATIONS = Path(__file__).parent / "migrations"
SCHEMA_VERSION = 17  # 0017_snapshot_categories
log = get_logger("hub.finance")
SEVERITY: dict[str, Severity] = {"budget_over": "alert", "budget_likely": "warning"}


def _read_period(dbapi_conn: sqlite3.Connection, _record: Any, _proxy: Any) -> None:
    """Chaque connexion relit le début du mois budgétaire : un réglage changé par l'app vaut
    aussitôt pour le planificateur et le CLI, qui tournent dans d'autres processus."""
    try:
        row = dbapi_conn.execute("SELECT start_day FROM budget_period").fetchone()
    except sqlite3.OperationalError:  # base pas encore migrée
        row = None
    period.set_start_day(int(row[0]) if row else 1)


class CurrencyMismatch(RuntimeError):
    pass


class FinanceDomain:
    name = "finance"
    description = manifest.DESCRIPTION
    schema_version = SCHEMA_VERSION
    scopes = frozenset({"finance:read", "finance:propose", "finance:aggregates"})

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.path = settings.db_path("finance")
        self._engine = make_engine(self.path)
        event.listen(self._engine, "checkout", _read_period)
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
        self.proposal_kinds: Mapping[str, ProposalKind] = build_kinds(self)

    def pillar3a(self) -> dict[str, Any]:
        """Options du pilier 3a pour les chiffres clés et les sentinelles : le module s'ouvre
        selon le pays du profil (Suisse)."""
        return {
            "pillar3a": profile.load(self.settings).has("pillar3a"),
            "pillar3a_cap": self.pillar3a_cap,
        }

    def manifest(self) -> Manifest:
        return manifest.MANIFEST

    def observations(self, limit: int) -> list[Observation]:
        """Les alertes des sentinelles des 31 derniers jours, en constats."""
        with self._engine.connect() as conn:
            alerts = sentinels.recent(conn, self.today())[:limit]
        return [
            Observation(
                a["key"],
                a["kind"],
                SEVERITY.get(a["kind"], "info"),
                a["title"],
                a["on_date"],
                detail=a["detail"],
            )
            for a in alerts
        ]

    def engine(self) -> Engine:
        return self._engine

    def migrate(self, *, seed: bool = True) -> None:
        """Migre ; une base neuve reçoit les packs de règles `base` et celui du pays du profil
        (`seed=False` pour une reconstruction, qui recopie les règles de la base d'origine)."""
        fresh = runner.current(MIGRATIONS, self.path) is None
        runner.upgrade(MIGRATIONS, self.path)
        self.check_currency()
        if fresh and seed:
            with begin_immediate(self._engine) as conn:
                for pack in packs.defaults_for(profile.load(self.settings).country):
                    packs.install(conn, pack, run=False)

    def recorded_currency(self) -> str:
        with self._engine.connect() as conn:
            return str(conn.execute(text("SELECT code FROM base_currency")).scalar_one())

    def check_currency(self) -> None:
        """La devise de base est fixée à la création de la base : `HUB_CURRENCY` doit la suivre."""
        recorded, wanted = self.recorded_currency(), base_currency()
        if recorded != wanted:
            raise CurrencyMismatch(
                f"finance.db est tenue en {recorded}, HUB_CURRENCY demande {wanted} : "
                f"remettre HUB_CURRENCY={recorded} dans deploy/.env"
            )

    def is_current(self) -> bool:
        return runner.current(MIGRATIONS, self.path) == runner.head(MIGRATIONS)

    def router(self) -> APIRouter:
        from hub.domains.finance.api import build_router

        return build_router(self)

    def cli(self) -> typer.Typer | None:
        from hub.domains.finance.cli import build_cli

        return build_cli(self)

    def mcp_tools(self) -> list[McpTool]:
        from hub.domains.finance.tools import FinanceTools

        return FinanceTools(self).build()

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
                        value,
                        ledger.party(row[0]) or row[1] or "écriture",
                        row[2],
                        f"/finance/entries/{u.id}",
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
            return integrity.events_since(conn, cursor, limit)

    def applied(self, proposal_ids: Sequence[str]) -> Mapping[str, dict[str, Any]]:
        with self._engine.connect() as conn:
            return integrity.applied(conn, proposal_ids)

    def record_applied(
        self, conn: Connection, proposal_id: str, kind: str, result: dict[str, Any]
    ) -> None:
        ledger.LEDGER.record_applied(conn, proposal_id, kind, result)

    def request_reviews(self) -> int:
        """Redemande une carte `apply_import` pour chaque import en attente : une carte expirée
        est ainsi régénérée tant que l'import reste à valider (création idempotente)."""
        with begin_immediate(self._engine) as conn:
            ids = conn.execute(
                text("SELECT id FROM imports WHERE status = 'needs_review' ORDER BY received_at")
            ).scalars()
            return sum(importer.request_review(conn, i) for i in list(ids))

    def verify_ledger(self) -> ledger.VerifyResult:
        with self._engine.connect() as conn:
            return ledger.verify(conn)

    def today(self) -> date:
        """Date civile de l'instance : fixe « aujourd'hui » pour les chiffres de l'app."""
        return local_today()

    def refresh_snapshots(self, *, force: bool = False) -> snapshots.Refresh:
        refreshed = snapshots.refresh(self._engine, self.today(), force=force)
        if refreshed.recomputed:
            self.refresh_derived()
        return refreshed

    def refresh_derived(self) -> dict[str, int]:
        """Virements appariés, puis abonnements (qui laissent les virements de côté)."""
        with begin_immediate(self._engine) as conn:
            pairs = transfers.refresh(conn)
            found = recurring.refresh(conn, self.today())
        log.info("derived.refreshed", transfers=pairs, recurring=found)
        return {"transfers": pairs, "recurring": found}

    def run_sentinels(self) -> list[sentinels.Alert]:
        with begin_immediate(self._engine) as conn:
            raised = sentinels.run(conn, self.today(), **self.pillar3a())
        for a in raised:
            log.info("sentinel.alert", kind=a.kind)
        return raised

    def nightly(self) -> None:
        refreshed = self.refresh_snapshots(force=True)
        log.info("snapshots.nightly", rows=refreshed.rows)
        log.info("imports.review_requested", count=self.request_reviews())
        log.info("sentinels.raised", count=len(self.run_sentinels()))
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
            if current:
                self.check_currency()
        except CurrencyMismatch:
            return Health(ok=False, db="currency_mismatch", schema_version=self.schema_version)
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
