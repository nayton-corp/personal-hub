"""Routes du registre : écritures, recherche, catégories, fraîcheur des comptes, export CSV et
lecture du mois budgétaire (son jour de début se change par la proposition `set_month_start`)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from hub.core.auth import AppSession
from hub.core.errors import Problem
from hub.domains.finance import thresholds
from hub.domains.finance.registre.app import export, period_kinds, reads
from hub.domains.finance.registre.interface import http
from hub.domains.finance.registre.interface.http import (
    DATE,
    AnyReader,
    Reader,
)
from hub.domains.finance.registre.interface.schemas import (
    CategoryListOut,
    EntryDetailOut,
    EntryListOut,
    EntrySearchOut,
    FreshnessListOut,
    SettingsOut,
    TradeListOut,
)
from hub.domains.finance.registre.model import period


def build_router(host: http.Host) -> APIRouter:
    r = APIRouter()
    engine = host.engine()

    def _settings() -> dict[str, Any]:
        with engine.connect() as conn:  # relit les règles (FinanceDomain)
            rules = period_kinds.rules_read(conn)
        today = host.today()
        month = period.month_of(today)
        start, end = period.bounds(month)
        return {
            "month_start_day": period.start_day(month),
            "current_month": month,
            "current_period": {"start": start.isoformat(), "end": end.isoformat()},
            "rules": [{"valid_from": v, "start_day": d} for v, d in dict(rules).items()],
            "stale_days": thresholds.current().stale_account_days,
        }

    @r.get("/entries", response_model=EntryListOut)
    def entries(
        _p: Reader,
        account: str | None = None,
        from_: Annotated[str | None, Query(alias="from", pattern=DATE)] = None,
        to: Annotated[str | None, Query(pattern=DATE)] = None,
        category: str | None = None,
        uncategorized: bool = False,
        direction: Annotated[str | None, Query(pattern=r"^(in|out)$")] = None,
        min_minor: Annotated[int | None, Query(ge=0)] = None,
        max_minor: Annotated[int | None, Query(ge=0)] = None,
        q: Annotated[str | None, Query(max_length=100)] = None,
        sort: Annotated[str, Query(pattern=r"^(date|amount)$")] = "date",
        cursor: Annotated[str | None, Query(max_length=40)] = None,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
    ) -> dict[str, Any]:
        """Écritures filtrées ; montants en centimes, comparés en valeur absolue."""
        f = reads.EntryFilter(
            account, from_, to, category, uncategorized, direction, min_minor, max_minor, q, sort
        )
        try:
            with engine.connect() as conn:
                items, next_cursor = reads.entries(conn, f, cursor, limit)
        except ValueError:
            raise Problem("validation.params", "curseur invalide") from None
        return {"items": items, "next_cursor": next_cursor}

    @r.get("/trades", response_model=TradeListOut)
    def trades_route(
        _p: Reader, isin: Annotated[str, Query(max_length=40)], account: str | None = None
    ) -> dict[str, Any]:
        """Achats et ventes d'un actif (ordres), pour le journal d'un actif dans l'app."""
        with engine.connect() as conn:
            return {"items": reads.trades(conn, isin, account)}

    @r.get("/entries/{entry_id}", response_model=EntryDetailOut)
    def entry(_p: Reader, entry_id: str) -> dict[str, Any]:
        with engine.connect() as conn:
            found = reads.entry_detail(conn, entry_id)
        if found is None:
            raise Problem("not_found")
        return found

    @r.get("/search", response_model=EntrySearchOut)
    def search(
        _p: Reader, q: Annotated[str, Query(min_length=3, max_length=100)]
    ) -> dict[str, Any]:
        if reads.fts_query(q) is None:
            raise Problem("validation.params", "au moins 3 caractères")
        with engine.connect() as conn:
            return {"items": reads.search(conn, q)}

    @r.get("/categories", response_model=CategoryListOut)
    def categories(_p: AnyReader) -> dict[str, Any]:
        with engine.connect() as conn:
            return {"items": reads.categories(conn)}

    @r.get("/freshness", response_model=FreshnessListOut)
    def freshness(_p: AnyReader) -> dict[str, Any]:
        with engine.connect() as conn:
            return {"items": reads.freshness(conn)}

    @r.get("/export.csv", response_class=StreamingResponse)
    def export_csv(
        _session: AppSession,
        from_: Annotated[str | None, Query(alias="from", pattern=DATE)] = None,
        to: Annotated[str | None, Query(pattern=DATE)] = None,
    ) -> StreamingResponse:
        """Journal complet en CSV (UTF-8, séparateur virgule) : tout s'exporte."""

        def body() -> Any:
            with engine.connect() as conn:
                yield from export.export_csv(conn, from_, to)

        name = f"finance-{host.today().isoformat()}.csv"
        return StreamingResponse(
            body(),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{name}"'},
        )

    @r.get("/settings", response_model=SettingsOut)
    def get_settings(_p: AnyReader) -> dict[str, Any]:
        """Réglages du budget : jour où commence le mois en cours, mois en cours et ses dates,
        règles datées (`set_month_start` en pose une nouvelle)."""
        return _settings()

    return r
