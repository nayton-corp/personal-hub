"""Routes Finance (section 6) : lecture du registre et dépôt d'un relevé."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse

from hub.core import profile, proposals
from hub.core.auth import AppSession, Ctx, Principal, require
from hub.core.errors import Problem
from hub.domains.finance import (
    catalog,
    insights,
    lookthrough,
    packs,
    reads,
    recurring,
    rules,
    sentinels,
    snapshots,
    transfers,
)
from hub.domains.finance.importer import APPLY_IMPORT, ImportRefused

if TYPE_CHECKING:
    from hub.domains.finance.domain import FinanceDomain

MONTH = r"^\d{4}-(0[1-9]|1[0-2])$"
PERIOD = r"^[mq]$"
DATE = r"^\d{4}-\d{2}-\d{2}$"
MAX_UPLOAD = 50 * 1024 * 1024
_NAME = re.compile(r"^[A-Za-z0-9._ -]{1,120}\.(xml|zip|pdf|json|csv|xlsx)$", re.I)
DIMENSION = r"^(region|sector|currency|holding)$"
_REVOLUT_REF = re.compile(r"revolut:([A-Z]{3})(:[a-z0-9-]+)?")

Reader = Annotated[Principal, Depends(require("app", "finance:read"))]
AnyReader = Annotated[Principal, Depends(require("app", "finance:read", "finance:aggregates"))]


def _aggregates_only(p: Principal) -> bool:
    return not (p.is_app or p.allows("finance:read"))


def build_router(domain: FinanceDomain) -> APIRouter:
    r = APIRouter()
    engine = domain.engine()

    def _this_month() -> str:
        return domain.today().strftime("%Y-%m")

    def _month(month: str | None) -> str:
        """Mois demandé (mois en cours par défaut) ; un mois futur n'a pas encore de chiffres."""
        value = month or _this_month()
        try:
            insights.as_of(value, domain.today())
        except insights.FutureMonth:
            raise Problem("validation.params", "mois futur") from None
        return value

    @r.get("/accounts")
    def accounts(_p: AnyReader) -> dict[str, Any]:
        """Comptes, IBAN masqué, solde calculé, dernier CLBD et écart."""
        with engine.connect() as conn:
            return {"items": reads.accounts(conn)}

    @r.get("/entries")
    def entries(
        _p: Reader,
        account: str | None = None,
        from_: Annotated[str | None, Query(alias="from", pattern=DATE)] = None,
        to: Annotated[str | None, Query(pattern=DATE)] = None,
        category: str | None = None,
        uncategorized: bool = False,
        direction: Annotated[str | None, Query(pattern=r"^(in|out)$")] = None,
        cursor: Annotated[str | None, Query(max_length=40)] = None,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
    ) -> dict[str, Any]:
        f = reads.EntryFilter(account, from_, to, category, uncategorized, direction)
        try:
            with engine.connect() as conn:
                items, next_cursor = reads.entries(conn, f, cursor, limit)
        except ValueError:
            raise Problem("validation.params", "curseur invalide") from None
        return {"items": items, "next_cursor": next_cursor}

    @r.get("/entries/{entry_id}")
    def entry(_p: Reader, entry_id: str) -> dict[str, Any]:
        with engine.connect() as conn:
            found = reads.entry_detail(conn, entry_id)
        if found is None:
            raise Problem("not_found")
        return found

    @r.get("/summary")
    def summary(
        p: AnyReader, month: Annotated[str | None, Query(pattern=MONTH)] = None
    ) -> dict[str, Any]:
        with engine.connect() as conn:
            return reads.summary(conn, _month(month), aggregates_only=_aggregates_only(p))

    @r.get("/budget")
    def budget(
        p: AnyReader,
        month: Annotated[str | None, Query(pattern=MONTH)] = None,
        period: Annotated[str, Query(pattern=PERIOD)] = "m",
    ) -> dict[str, Any]:
        """Réel et cible par catégorie de dépense, dépassements, reste à vivre, jours restants.
        `period=q` : les trois mois complets avant `month`."""
        m = _month(month)
        with engine.connect() as conn:
            return insights.budget(
                conn, m, period, domain.today(), aggregates_only=_aggregates_only(p)
            )

    @r.get("/budget/totals")
    def budget_totals(
        _p: AnyReader,
        month: Annotated[str | None, Query(pattern=MONTH)] = None,
        period: Annotated[str, Query(pattern=PERIOD)] = "m",
    ) -> dict[str, Any]:
        """Revenus, dépenses (fixes, variables), épargne, placements et taux d'épargne."""
        m = _month(month)
        with engine.connect() as conn:
            return insights.budget_totals(conn, m, period)

    @r.get("/budget/months")
    def budget_months(
        _p: AnyReader,
        month: Annotated[str | None, Query(pattern=MONTH)] = None,
        months: Annotated[int, Query(ge=1, le=36)] = 6,
    ) -> dict[str, Any]:
        """Les totaux du budget mois par mois, jusqu'à `month` compris."""
        m = _month(month)
        with engine.connect() as conn:
            return insights.budget_months(conn, m, months)

    @r.get("/kpis")
    def kpis(
        _p: AnyReader, month: Annotated[str | None, Query(pattern=MONTH)] = None
    ) -> dict[str, Any]:
        """Chiffres clés de l'accueil : patrimoine et variations, mois, liquidités, à traiter."""
        m = _month(month)
        with engine.connect() as conn:
            return insights.kpis(conn, m, domain.today(), **domain.pillar3a())

    @r.get("/holdings")
    def holdings(
        _p: AnyReader, on: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}-\d{2}$")] = None
    ) -> dict[str, Any]:
        """Positions des comptes de titres (VIAC) à une date, aujourd'hui par défaut."""
        with engine.connect() as conn:
            return insights.holdings(conn, on or domain.today().isoformat())

    @r.get("/lookthrough")
    def lookthrough_route(
        _p: AnyReader,
        dimension: Annotated[str, Query(pattern=DIMENSION)] = "region",
        on: Annotated[str | None, Query(pattern=DATE)] = None,
    ) -> dict[str, Any]:
        """Positions ventilées par région, secteur, devise, ou les dix plus grosses lignes
        sous-jacentes (transparence des fonds)."""
        with engine.connect() as conn:
            return lookthrough.breakdown(conn, dimension, on or domain.today().isoformat())

    @r.get("/recurring")
    def recurring_route(p: AnyReader) -> dict[str, Any]:
        """Abonnements et paiements réguliers, prochaines échéances, total mensuel ; pour la
        portée `aggregates`, les totaux seulement."""
        domain.refresh_snapshots()
        with engine.connect() as conn:
            return recurring.listing(conn, domain.today(), aggregates_only=_aggregates_only(p))

    @r.get("/transfers")
    def transfers_route(p: AnyReader) -> dict[str, Any]:
        """Virements appariés par méthode et virements sans autre côté."""
        domain.refresh_snapshots()
        with engine.connect() as conn:
            return transfers.summary(conn, detailed=not _aggregates_only(p))

    @r.get("/networth/history")
    def networth_history(
        _p: AnyReader,
        from_: Annotated[str | None, Query(alias="from", pattern=DATE)] = None,
        to: Annotated[str | None, Query(pattern=DATE)] = None,
        step: Annotated[str, Query(pattern=r"^(day|week|month)$")] = "month",
    ) -> dict[str, Any]:
        """Instantanés : patrimoine, versements cumulés, valeur par enveloppe et par compte.
        `step=day` ou `week` : un point par jour ou par semaine, calculé à la demande entre
        `from` et `to` (aujourd'hui par défaut), au plus 400 points."""
        if step != "month":
            if from_ is None:
                raise Problem("validation.params", "from requis pour un pas jour ou semaine")
            dates = snapshots.steps(from_, to or domain.today().isoformat(), step)
            if not dates or len(dates) > snapshots.MAX_LIVE_POINTS:
                raise Problem("validation.params", "période vide ou trop longue pour ce pas")
            with engine.connect() as conn:
                return snapshots.live_history(conn, dates)
        domain.refresh_snapshots()
        with engine.connect() as conn:
            return snapshots.history(conn, from_, to)

    @r.get("/flows")
    def flows(
        p: AnyReader,
        month: Annotated[str | None, Query(pattern=MONTH)] = None,
        period: Annotated[str, Query(pattern=PERIOD)] = "m",
    ) -> dict[str, Any]:
        """Revenus → groupes (fixe, variable, épargne) → catégories, et le reste sur compte.
        `period=q` : les trois mois complets avant `month`, comme le budget."""
        m = _month(month)
        with engine.connect() as conn:
            return insights.flows(conn, m, aggregates_only=_aggregates_only(p), period=period)

    @r.get("/export.csv", response_class=StreamingResponse)
    def export_csv(
        _session: AppSession,
        from_: Annotated[str | None, Query(alias="from", pattern=DATE)] = None,
        to: Annotated[str | None, Query(pattern=DATE)] = None,
    ) -> StreamingResponse:
        """Journal complet en CSV (UTF-8, séparateur virgule) : tout s'exporte."""

        def body() -> Any:
            with engine.connect() as conn:
                yield from insights.export_csv(conn, from_, to)

        name = f"finance-{domain.today().isoformat()}.csv"
        return StreamingResponse(
            body(),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{name}"'},
        )

    @r.get("/trend")
    def trend(
        _p: AnyReader,
        category: str | None = None,
        months: Annotated[int, Query(ge=1, le=36)] = 12,
        month: Annotated[str | None, Query(pattern=MONTH)] = None,
    ) -> dict[str, Any]:
        with engine.connect() as conn:
            series = reads.trend(conn, category, months, month or _this_month())
        return {"category": category, "series": series}

    @r.get("/review")
    def review(_p: Reader) -> dict[str, Any]:
        """Écritures sans catégorie, groupées par contrepartie normalisée."""
        with engine.connect() as conn:
            return {"groups": reads.review(conn)}

    @r.get("/search")
    def search(
        _p: Reader, q: Annotated[str, Query(min_length=3, max_length=100)]
    ) -> dict[str, Any]:
        if reads.fts_query(q) is None:
            raise Problem("validation.params", "au moins 3 caractères")
        with engine.connect() as conn:
            return {"items": reads.search(conn, q)}

    @r.get("/alerts")
    def alerts(_p: Reader) -> dict[str, Any]:
        """Alertes des sentinelles des 31 derniers jours (budget, abonnements, 3a)."""
        with engine.connect() as conn:
            return {"items": sentinels.recent(conn, domain.today())}

    @r.get("/categories")
    def categories(_p: AnyReader) -> dict[str, Any]:
        with engine.connect() as conn:
            return {"items": reads.categories(conn)}

    @r.get("/rules/packs")
    def rule_packs(_p: Reader) -> dict[str, Any]:
        """Packs de règles livrés, version installée, ceux du pays de l'instance, et le nombre
        de règles actives hors système (parcours d'accueil)."""
        country = profile.load(domain.settings).country
        with engine.connect() as conn:
            done = packs.installed(conn)
            active = sum(
                1
                for x in rules.list_rules(conn)
                if x.active and not x.id.startswith(rules.SYSTEM_PREFIX)
            )
        return {
            "items": [
                {
                    "name": p.name,
                    "label": p.label,
                    "description": p.description,
                    "country": p.country,
                    "version": p.version,
                    "installed": done.get(p.name),
                    "rules": len(p.specs()),
                }
                for p in packs.available().values()
            ],
            "suggested": [p.name for p in packs.defaults_for(country)],
            "active_rules": active,
        }

    @r.get("/accounts/pending")
    def pending_accounts(_p: Reader) -> dict[str, Any]:
        """Comptes vus dans des relevés en attente (Enable Banking, CSV Revolut) mais pas encore
        créés : clé, devise, nombre d'écritures et période. Aucun montant."""
        from hub.domains.finance import importer

        out = []
        for ref, items in sorted(importer.revolut_pending(domain.importer).items()):
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

    @r.get("/freshness")
    def freshness(_p: AnyReader) -> dict[str, Any]:
        with engine.connect() as conn:
            return {"items": reads.freshness(conn)}

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
            report = domain.importer.receive(name, body)
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
