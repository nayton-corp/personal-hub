"""Domaine Agenda (chantier S11) : Rappels et Calendrier du Mac, par le pont EventKit.

Le premier domaine réel monté sans toucher au cœur. Il ne garde aucune copie des rappels ni
des événements : il les lit au pont, et chaque écriture (ajouter, cocher) est une proposition à
effet externe. Jamais de suppression. Le pont absent (Mac éteint, autorisation de macOS
retirée), le domaine le dit et le reste du hub continue.
"""

from __future__ import annotations

import base64
from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import typer
from fastapi import APIRouter
from sqlalchemy import Connection, Engine

from hub.core import integrity
from hub.core.domain import Event, Health, Hit, McpTool, ProposalKind, Ref
from hub.core.manifest import AppModule, HomeCard, Manifest, Observation
from hub.core.search import excerpt
from hub.domains.agenda import api, tools
from hub.domains.agenda.bridge import SHOPPING, Bridge, BridgeError, Transport
from hub.domains.agenda.kinds import kinds
from hub.kernel.clock import local_today
from hub.kernel.ids import Urn, urn
from hub.platform import migrations as runner
from hub.platform.db import make_engine
from hub.platform.settings import Settings

MIGRATIONS = Path(__file__).parent / "migrations"
SCHEMA_VERSION = 1  # 0001_agenda
LEDGER = integrity.Ledger(integrity.COMMON_FIELDS)
DEFAULT_BRIDGE = "http://host.docker.internal:8771"  # le pont, sur le Mac qui porte les conteneurs
WEEK = 7

MANIFEST = Manifest(
    description="Agenda : rappels, liste de courses et calendrier du Mac (Rappels, Calendrier).",
    app=AppModule(
        home_cards=(HomeCard("agenda", "Agenda", "/overview"),),
        home="home.js",
        web=Path(__file__).parent / "web",
    ),
    protected_tables=frozenset({"events", "applied_proposals"}),
    assistant=(
        "Les rappels et les événements vivent dans Rappels et Calendrier : un ajout ou une case "
        "cochée est une proposition, jamais une suppression. La liste de courses s'enrichit sans "
        "carte (agenda_add_shopping). Toujours dire la date d'un événement."
    ),
)


def ref_of(item_id: str) -> str:
    """Les identifiants d'EventKit contiennent « : » : base64 sans remplissage dans l'URN."""
    return base64.urlsafe_b64encode(item_id.encode()).decode().rstrip("=")


def id_of(ref: str) -> str:
    return base64.urlsafe_b64decode(ref + "=" * (-len(ref) % 4)).decode()


class AgendaDomain:
    name = "agenda"
    description = MANIFEST.description
    schema_version = SCHEMA_VERSION
    scopes = frozenset({"agenda:read", "agenda:propose", "agenda:aggregates"})

    def __init__(self, settings: Settings, transport: Transport | None = None) -> None:
        self.settings = settings
        self.path = settings.db_path(self.name)
        self._engine = make_engine(self.path)
        section = settings.domain(self.name)
        self.bridge = Bridge(section.get("bridge_url", DEFAULT_BRIDGE), transport)
        self.proposal_kinds: Mapping[str, ProposalKind] = kinds(self.engine, self.bridge)

    # --- lectures, au pont ------------------------------------------------------------------

    def today(self) -> date:
        return local_today()

    def upcoming(self, days: int = WEEK) -> dict[str, Any]:
        """Les événements des prochains jours, les rappels ouverts et la liste de courses."""
        start = self.today()
        events = self.bridge.events(start.isoformat(), (start + timedelta(days=days)).isoformat())
        reminders = self.bridge.reminders()
        return {
            "from": start.isoformat(),
            "days": days,
            "events": events,
            "reminders": [r for r in reminders if r.get("list") != SHOPPING],
            "shopping": [r for r in reminders if r.get("list") == SHOPPING],
        }

    def overview(self) -> dict[str, Any]:
        """Le bloc de l'accueil : jamais une erreur, le pont absent se dit."""
        try:
            found = self.upcoming()
        except BridgeError as exc:
            return {"available": False, "reason": str(exc)}
        # l'accueil ne liste que les rappels en retard ou du jour ; les autres se comptent
        today = self.today()
        overdue = [r for r in found["reminders"] if _overdue(r, today)]
        now = [r for r in found["reminders"] if _overdue(r, today) or _due_today(r, today)]
        return {
            "available": True,
            **found,
            "reminders": now,
            "open_reminders": len(found["reminders"]),
            "overdue": len(overdue),
        }

    def counts(self) -> dict[str, Any]:
        """Les agrégats : combien, jamais quoi."""
        found = self.upcoming()
        return {
            "from": found["from"],
            "days": found["days"],
            "events": len(found["events"]),
            "open_reminders": len(found["reminders"]),
            "overdue": sum(_overdue(r, self.today()) for r in found["reminders"]),
            "shopping": len(found["shopping"]),
        }

    # --- contrat de domaine ------------------------------------------------------------------

    def manifest(self) -> Manifest:
        return MANIFEST

    def observations(self, limit: int) -> list[Observation]:
        try:
            n = self.counts()["overdue"]
        except BridgeError:
            return []
        if not n or limit < 1:
            return []
        title = f"{n} rappel{'s' if n > 1 else ''} en retard"
        return [
            Observation("agenda-overdue", "overdue", "warning", title, self.today().isoformat())
        ]

    def process_inbox(self) -> dict[str, int]:
        return {}  # l'agenda ne réclame aucun fichier

    def engine(self) -> Engine:
        return self._engine

    def migrate(self) -> None:
        runner.upgrade(MIGRATIONS, self.path)

    def is_current(self) -> bool:
        return runner.current(MIGRATIONS, self.path) == runner.head(MIGRATIONS)

    def router(self) -> APIRouter:
        return api.build_router(self)

    def cli(self) -> typer.Typer | None:
        return api.build_cli(self)

    def mcp_tools(self) -> list[McpTool]:
        return tools.build(self)

    def search(self, q: str, limit: int, scopes: frozenset[str]) -> list[Hit]:
        try:
            found = self.upcoming(days=31)
        except BridgeError:
            return []
        needle = q.casefold()
        hits: list[Hit] = []
        for kind, items in (("event", found["events"]), ("reminder", found["reminders"])):
            for item in items:
                title = str(item.get("title") or "")
                if needle in title.casefold() or needle in str(item.get("notes") or "").casefold():
                    when = str(item.get("start") or item.get("due") or "")[:10] or None
                    # le plus proche d'abord : un score plus grand pour une date plus tôt
                    score = -int((when or "9999-12-31").replace("-", ""))
                    ref = urn(self.name, kind, ref_of(str(item["id"])))
                    hits.append(
                        Hit(ref, title, when, score, excerpt([item.get("notes"), title], q))
                    )
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:limit]

    def resolve(self, value: str) -> Ref | None:
        u = Urn.parse(value)
        try:
            item_id = id_of(u.id)
            if u.type == "reminder":
                found = [
                    r for r in self.bridge.reminders(None, done=True) if r.get("id") == item_id
                ]
            elif u.type == "event":
                start = self.today() - timedelta(days=366)
                end = self.today() + timedelta(days=366)
                found = [
                    e
                    for e in self.bridge.events(start.isoformat(), end.isoformat())
                    if e.get("id") == item_id
                ]
            else:
                return None
        except (BridgeError, ValueError):
            return None
        if not found:
            return None
        item = found[0]
        when = str(item.get("start") or item.get("due") or "")[:10] or None
        return Ref(value, str(item.get("title") or ""), when, f"/agenda/{u.type}s/{u.id}")

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

    def nightly(self) -> None:
        return None  # rien à recalculer : l'agenda vit dans Rappels et Calendrier

    def bridge_status(self) -> dict[str, Any]:
        try:
            return {"bridge": "ok", **self.bridge.status()}
        except BridgeError as exc:
            return {"bridge": "unreachable" if exc.unreachable else "refused", "error": str(exc)}

    def health(self) -> Health:
        """La base fait la santé ; le pont n'est qu'un détail (le Mac peut dormir)."""
        if not self.path.exists():
            return Health(ok=False, db="missing", schema_version=self.schema_version)
        try:
            current = self.is_current()
        except Exception:
            return Health(ok=False, db="error", schema_version=self.schema_version)
        return Health(
            ok=current,
            db="ok" if current else "outdated",
            schema_version=self.schema_version,
            detail=self.bridge_status(),
        )

    def verify(self) -> Health:
        health = self.health()
        if not health.ok:
            return health
        with self._engine.connect() as conn:
            result = LEDGER.verify(conn)
        return Health(
            ok=result.ok,
            db=health.db,
            schema_version=self.schema_version,
            detail={"ledger": result.public()},
        )


def _overdue(reminder: dict[str, Any], today: date) -> bool:
    due = str(reminder.get("due") or "")[:10]
    return bool(due) and not reminder.get("done") and due < today.isoformat()


def _due_today(reminder: dict[str, Any], today: date) -> bool:
    return not reminder.get("done") and str(reminder.get("due") or "")[:10] == today.isoformat()


def create(settings: Settings) -> AgendaDomain:
    """Point d'entrée `hub.domains` (pyproject.toml)."""
    return AgendaDomain(settings)
