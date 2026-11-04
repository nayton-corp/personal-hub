"""Routes des sources : dépôt d'un relevé (même traitement que `inbox/`), détail d'un import,
comptes vus dans des relevés en attente."""

from __future__ import annotations

import re
from typing import Annotated, Any, Protocol

from fastapi import APIRouter, Query, Request
from starlette.concurrency import run_in_threadpool

from hub.core import proposal_events, proposals
from hub.core.auth import AppSession, Ctx
from hub.core.body import read_body
from hub.core.errors import Problem
from hub.domains.finance.registre.app import reads
from hub.domains.finance.registre.interface import http
from hub.domains.finance.registre.interface.http import (
    Reader,
)
from hub.domains.finance.registre.model.errors import ImportRefused
from hub.domains.finance.sources.app.importer import ImportService
from hub.domains.finance.sources.app.statements import APPLY_IMPORT
from hub.domains.finance.sources.interface.schemas import (
    ImportDetailOut,
    PendingAccountsOut,
    UploadOut,
)
from hub.domains.finance.sources.interface.tools import pending_accounts

MAX_UPLOAD = 50 * 1024 * 1024
_NAME = re.compile(r"^[A-Za-z0-9._ -]{1,120}\.(xml|zip|pdf|json|csv|xlsx)$", re.I)


class Host(http.Host, Protocol):
    importer: ImportService


def build_router(host: Host) -> APIRouter:
    r = APIRouter()
    engine = host.engine()

    @r.get("/accounts/pending", response_model=PendingAccountsOut)
    def pending_accounts_route(_p: Reader) -> dict[str, Any]:
        """Comptes vus dans des relevés en attente (Enable Banking, CSV Revolut) mais pas encore
        créés : clé, devise, nombre d'écritures et période. Aucun montant."""
        return {"items": pending_accounts(host)}

    @r.post("/imports", status_code=202, response_model=UploadOut)
    async def upload(
        request: Request,
        _session: AppSession,
        name: Annotated[str, Query(max_length=124)],
    ) -> dict[str, Any]:
        """Corps brut (XML, zip, PDF VIAC, JSON, CSV ou relevé SwissBorg .xlsx) ; même traitement
        que `inbox/`."""
        if not _NAME.match(name):
            raise Problem(
                "validation.params", "nom de fichier .xml, .zip, .pdf, .json, .csv ou .xlsx"
            )
        body = await read_body(request, MAX_UPLOAD)  # en flux : rien gardé au-delà
        if not body:
            raise Problem("validation.params", "fichier vide ou trop volumineux")
        try:  # l'import bloque (lecture, application, instantanés) : hors de la boucle
            report = await run_in_threadpool(host.importer.receive, name, body)
        except ImportRefused as exc:
            headers = {"Retry-After": "60"} if exc.code == "busy.retry" else None
            raise Problem(exc.code, exc.detail, headers=headers) from None
        files = report.files
        if files and all(f.status == "duplicate" for f in files):
            raise Problem("import.duplicate_file")
        if files and all(f.status == "rejected" for f in files):
            raise Problem("import.invalid_schema", files[0].reason)
        with engine.connect() as conn:
            items = [
                {"import_id": f.import_id, "status": _status(conn, f.import_id) or f.status}
                for f in files
            ]
        return {"items": items, "counters": report.counters()}

    @r.get("/imports/{import_id}", response_model=ImportDetailOut)
    def import_detail(_session: AppSession, hub_ctx: Ctx, import_id: str) -> dict[str, Any]:
        with engine.connect() as conn:
            found = reads.import_detail(conn, import_id)
        if found is None:
            raise Problem("not_found")
        proposal_events.sync_events(hub_ctx)
        card = proposals.find(hub_ctx, "finance", APPLY_IMPORT, {"import_id": import_id})
        return {**found, "proposal_id": card.id if card else None}

    return r


def _status(conn: Any, import_id: str | None) -> str | None:
    if import_id is None:
        return None
    found = reads.import_detail(conn, import_id)
    return str(found["status"]) if found else None
