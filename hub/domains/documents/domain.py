"""Domaine Documents (chantier S12) : fiches d'objets, documents, archive et index local.

Repris de la bibliothèque de l'assistant de Domia (`~/Domia/Bibliothèque/`, une fiche YAML par
objet et ses documents à côté), qui n'est plus lue après la reprise. Les fiches et les
documents sont des lignes en ajout seul, chaînées ; chaque fichier et chaque ligne vont aussi
dans une archive chiffrée, dont la base se reconstruit seule. Un document est privé tant qu'il
n'est pas marqué « foyer » : seuls ceux-là, et les fiches, sont lisibles par tout le foyer. Un
document se lie à une écriture de la finance (facture, garantie) par `core/link`.
"""

from __future__ import annotations

import base64
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any

import typer
from fastapi import APIRouter
from sqlalchemy import Connection, Engine

from hub.core import integrity
from hub.core.domain import Event, Health, Hit, McpTool, ProposalKind, Ref
from hub.core.manifest import AppModule, HomeCard, Importer, Manifest, Observation
from hub.core.search import excerpt
from hub.domains.documents import api, index, store, tools
from hub.domains.documents.archive import Archive
from hub.domains.documents.kinds import kinds
from hub.domains.documents.model import maintenance_due
from hub.domains.documents.service import Library
from hub.kernel.clock import local_today
from hub.kernel.ids import Urn, urn
from hub.platform import migrations as runner
from hub.platform.db import make_engine
from hub.platform.settings import Settings

MIGRATIONS = Path(__file__).parent / "migrations"
SCHEMA_VERSION = 1  # 0001_documents

MANIFEST = Manifest(
    description="Documents : fiches d'objets de la maison, notices, contrats et garanties.",
    app=AppModule(
        home_cards=(HomeCard("documents", "Documents", "/overview"),),
        home="home.js",
        web=Path(__file__).parent / "web",
    ),
    # la finance réclame les PDF : un PDF arrive par inbox/documents/ (raccourci, AirDrop)
    importers=(Importer("documents", "Courriels et notes", frozenset({".eml", ".md", ".txt"})),),
    protected_tables=frozenset({"cards", "documents", "marks", "events", "applied_proposals"}),
    assistant=(
        "Les fiches d'objets et les documents de la maison : toujours citer la source et la "
        "page d'un passage (champ cite). Une fiche se complète par une proposition "
        "(documents_propose_card), jamais en silence."
    ),
)


def ref_of(card_id: str) -> str:
    """Un id de fiche porte des espaces : base64 sans remplissage dans l'URN."""
    return base64.urlsafe_b64encode(card_id.encode()).decode().rstrip("=")


def id_of(ref: str) -> str:
    return base64.urlsafe_b64decode(ref + "=" * (-len(ref) % 4)).decode()


class DocumentsDomain:
    name = "documents"
    description = MANIFEST.description
    schema_version = SCHEMA_VERSION
    scopes = frozenset(
        {"documents:read", "documents:household", "documents:propose", "documents:aggregates"}
    )

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.path = settings.db_path(self.name)
        self._engine = make_engine(self.path)
        archive = Archive(settings.paths.archive_of(self.name), settings.secrets.age_key_file)
        self.library = Library(self.engine, archive)
        self.proposal_kinds: Mapping[str, ProposalKind] = kinds(self.library)

    def today(self) -> date:
        return local_today()

    # --- lectures -----------------------------------------------------------------------------

    def find(self, q: str, limit: int, household_only: bool) -> dict[str, Any]:
        """Les passages qui répondent (avec de quoi les citer) et les fiches qui en parlent."""
        with self._engine.connect() as conn:
            docs = {d["id"]: d for d in store.documents(conn, household_only=household_only)}
            found = index.search(conn, q, limit, set(docs) if household_only else None)
            cards = store.cards(conn)
        passages = []
        for p in found:
            doc = docs[p["document_id"]]
            cite = doc["title"] + (f", p. {p['page']}" if p["page"] else "")
            passages.append({**p, "title": doc["title"], "card_id": doc["card_id"], "cite": cite})
        needle = q.casefold()
        matching = [
            {"card_id": cid, "name": c.get("name", cid)}
            for cid, c in cards.items()
            if needle in f"{cid} {' '.join(map(str, c.values()))}".casefold()
        ]
        return {"passages": passages, "cards": matching[:limit]}

    def card_list(self) -> list[dict[str, Any]]:
        with self._engine.connect() as conn:
            cards = store.cards(conn)
        keep = ("name", "room", "brand", "model")
        return [{"card_id": cid, **{k: c.get(k) for k in keep}} for cid, c in cards.items()]

    def card_view(self, card_id: str, household_only: bool) -> dict[str, Any] | None:
        with self._engine.connect() as conn:
            card = store.card(conn, card_id)
            if card is None:
                return None
            docs = store.documents(conn, household_only=household_only, card_id=card_id)
        listed = [{k: d[k] for k in ("id", "title", "file_name", "household")} for d in docs]
        return {"card_id": card_id, **card, "files": listed}

    def due(self) -> list[dict[str, Any]]:
        with self._engine.connect() as conn:
            return maintenance_due(store.cards(conn), self.today())

    def counts(self) -> dict[str, int]:
        with self._engine.connect() as conn:
            docs = store.documents(conn)
            cards = store.cards(conn)
        return {
            "cards": len(cards),
            "documents": len(docs),
            "household": sum(d["household"] for d in docs),
            "maintenance_due": len(maintenance_due(cards, self.today())),
        }

    def overview(self) -> dict[str, Any]:
        with self._engine.connect() as conn:
            recent = store.documents(conn)[:5]
            cards = store.cards(conn)
        keep = ("id", "title", "card_id", "household", "at")
        return {
            **self.counts(),
            "due": self.due(),
            # le nom de la fiche dit de quoi parle un fichier nommé « manuel.pdf »
            "recent": [
                {
                    **{k: d[k] for k in keep},
                    "card_name": (cards.get(d["card_id"]) or {}).get("name"),
                }
                for d in recent
            ],
        }

    # --- écritures et reconstruction ----------------------------------------------------------

    def import_library(self, folder: Path) -> dict[str, int]:
        return self.library.import_library(folder)

    def reindex(self) -> int:
        return self.library.reindex()

    def _fresh(self, path: Path) -> Engine:
        runner.upgrade(MIGRATIONS, path)
        return make_engine(path)

    def rebuild(self) -> dict[str, int]:
        return self.library.rebuild(self._engine)

    def compare(self) -> dict[str, Any]:
        return self.library.compare(self._fresh)

    # --- contrat de domaine -------------------------------------------------------------------

    def manifest(self) -> Manifest:
        return MANIFEST

    def observations(self, limit: int) -> list[Observation]:
        out = [
            Observation(
                f"documents-due-{ref_of(d['card'])}-{d['since']}",
                "maintenance_due",
                "info",
                f"Entretien : {d['name']} ({d['what']})",
                d["since"],
                urn(self.name, "card", ref_of(d["card"])),
            )
            for d in self.due()
        ]
        out.sort(key=lambda o: o.on_date, reverse=True)
        return out[:limit]

    def process_inbox(self) -> dict[str, int]:
        return self.library.process_inbox(self.settings.paths.inbox_of(self.name))

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
        found = self.find(q, limit, household_only=False)
        hits: list[Hit] = []
        seen: set[str] = set()
        for rank, p in enumerate(found["passages"]):
            if p["document_id"] in seen:
                continue
            seen.add(p["document_id"])
            ref = urn(self.name, "document", p["document_id"])
            hits.append(Hit(ref, p["cite"], None, 2 * limit - rank, excerpt([p["text"]], q)))
        for rank, c in enumerate(found["cards"]):
            ref = urn(self.name, "card", ref_of(c["card_id"]))
            hits.append(Hit(ref, str(c["name"]), None, limit - rank))
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:limit]

    def resolve(self, value: str) -> Ref | None:
        u = Urn.parse(value)
        with self._engine.connect() as conn:
            if u.type == "document":
                doc = store.document(conn, u.id)
                if doc is not None:
                    return Ref(value, doc["title"], doc["at"][:10], f"/documents/{u.id}")
            elif u.type == "card":
                try:
                    card_id = id_of(u.id)
                except ValueError:
                    return None
                card = store.card(conn, card_id)
                if card is not None:
                    return Ref(value, str(card.get("name", card_id)), None, f"/cards/{u.id}")
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
        store.LEDGER.record_applied(conn, proposal_id, kind, result)

    def nightly(self) -> None:
        """Rattrape l'archive (une ligne validée juste avant un arrêt) et l'index manquant."""
        self.library.export()
        self.library.reindex(missing_only=True)

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
        with self._engine.connect() as conn:
            result = store.LEDGER.verify(conn)
            lines = {t: len(store.rows(conn, t)) for t in ("cards", "documents", "marks")}
        archived = self.library.archive.counts()
        missing = {t: n - archived[t] for t, n in lines.items() if n > archived[t]}
        return Health(
            ok=result.ok,
            db=health.db,
            schema_version=self.schema_version,
            detail={"ledger": result.public(), "archive": archived, "not_archived": missing},
        )


def create(settings: Settings) -> DocumentsDomain:
    """Point d'entrée `hub.domains` (pyproject.toml)."""
    return DocumentsDomain(settings)
