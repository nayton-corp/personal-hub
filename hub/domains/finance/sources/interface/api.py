"""Routes des sources : dépôt d'un relevé (même traitement que `inbox/`), détail d'un import,
comptes vus dans des relevés en attente."""

from __future__ import annotations

import re
from typing import Annotated, Any, Protocol

from fastapi import APIRouter, Query, Request

from hub.core import proposals
from hub.core.auth import AppSession, Ctx
from hub.core.errors import Problem
from hub.domains.finance.registre.app import catalog, reads
from hub.domains.finance.registre.interface import http
from hub.domains.finance.registre.interface.http import (
    Reader,
)
from hub.domains.finance.registre.model.errors import ImportRefused
from hub.domains.finance.sources.app import revolut_accounts
from hub.domains.finance.sources.app.importer import ImportService
from hub.domains.finance.sources.app.statements import APPLY_IMPORT

MAX_UPLOAD = 50 * 1024 * 1024
_NAME = re.compile(r"^[A-Za-z0-9._ -]{1,120}\.(xml|zip|pdf|json|csv|xlsx)$", re.I)
_REVOLUT_REF = re.compile(r"revolut:([A-Z]{3})(:[a-z0-9-]+)?")


class Host(http.Host, Protocol):
    importer: ImportService


def build_router(host: Host) -> APIRouter:
    r = APIRouter()
    engine = host.engine()

    @r.get("/accounts/pending")
    def pending_accounts(_p: Reader) -> dict[str, Any]:
        """Comptes vus dans des relevés en attente (Enable Banking, CSV Revolut) mais pas encore
        créés : clé, devise, nombre d'écritures et période. Aucun montant."""
        out = []
        for ref, items in sorted(revolut_accounts.revolut_pending(host.importer).items()):
            with engine.connect() as conn:
                if catalog.account_by_ref(conn, ref) is not None:
                    continue
            dates = [e.booking_date for _, st in items for e in st.entries]
            m = _REVOLUT_REF.fullmatch(ref)
            out.append(
                {
                    "ref": ref,
                    "institution": "Revolut",
                    "kind": "cash",
                    "currency": m.group(1) if m else None,
                    "imports": len({i for i, _ in items}),
                    "entries": sum(len(st.entries) for _, st in items),
                    "from": min(dates, default=None),
                    "to": max(dates, default=None),
                    "can_open": any(st.derived_opening for _, st in items),
                }
            )
        return {"items": out}

    @r.post("/imports", status_code=202)
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
        body = await request.body()
        if not body or len(body) > MAX_UPLOAD:
            raise Problem("validation.params", "fichier vide ou trop volumineux")
        try:
            report = host.importer.receive(name, body)
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

    @r.get("/imports/{import_id}")
    def import_detail(_session: AppSession, hub_ctx: Ctx, import_id: str) -> dict[str, Any]:
        with engine.connect() as conn:
            found = reads.import_detail(conn, import_id)
        if found is None:
            raise Problem("not_found")
        proposals.sync_events(hub_ctx)
        card = proposals.find(hub_ctx, "finance", APPLY_IMPORT, {"import_id": import_id})
        return {**found, "proposal_id": card.id if card else None}

    return r


def _status(conn: Any, import_id: str | None) -> str | None:
    if import_id is None:
        return None
    found = reads.import_detail(conn, import_id)
    return str(found["status"]) if found else None
