"""Routes du classement et du budget : résumé et tendance par catégorie, budget du mois, flux,
écritures à revoir, alertes, packs de règles, abonnements."""

from __future__ import annotations

from typing import Annotated, Any, Protocol

from fastapi import APIRouter, Query

from hub.core import profile
from hub.domains.finance.classement.app import budget as budget_app
from hub.domains.finance.classement.app import packs, recurring, rules, sentinels, totals
from hub.domains.finance.classement.app import review as reviewing
from hub.domains.finance.registre.interface import http
from hub.domains.finance.registre.interface.http import (
    MONTH,
    PERIOD,
    AnyReader,
    Reader,
    aggregates_only,
    checked_month,
    this_month,
)


class Host(http.Host, Protocol):
    def refresh_snapshots(self) -> object: ...


def build_router(host: Host) -> APIRouter:
    r = APIRouter()
    engine = host.engine()

    @r.get("/summary")
    def summary(
        p: AnyReader, month: Annotated[str | None, Query(pattern=MONTH)] = None
    ) -> dict[str, Any]:
        with engine.connect() as conn:
            return totals.summary(
                conn, checked_month(host, month), aggregates_only=aggregates_only(p)
            )

    @r.get("/budget")
    def budget(
        p: AnyReader,
        month: Annotated[str | None, Query(pattern=MONTH)] = None,
        period: Annotated[str, Query(pattern=PERIOD)] = "m",
    ) -> dict[str, Any]:
        """Réel et cible par catégorie de dépense, dépassements, reste à vivre, jours restants.
        `period=q` : les trois mois complets avant `month`."""
        m = checked_month(host, month)
        with engine.connect() as conn:
            return budget_app.budget(
                conn, m, period, host.today(), aggregates_only=aggregates_only(p)
            )

    @r.get("/budget/totals")
    def budget_totals(
        _p: AnyReader,
        month: Annotated[str | None, Query(pattern=MONTH)] = None,
        period: Annotated[str, Query(pattern=PERIOD)] = "m",
    ) -> dict[str, Any]:
        """Revenus, dépenses (fixes, variables), épargne, placements et taux d'épargne."""
        m = checked_month(host, month)
        with engine.connect() as conn:
            return budget_app.budget_totals(conn, m, period)

    @r.get("/budget/months")
    def budget_months(
        _p: AnyReader,
        month: Annotated[str | None, Query(pattern=MONTH)] = None,
        months: Annotated[int, Query(ge=1, le=36)] = 6,
    ) -> dict[str, Any]:
        """Les totaux du budget mois par mois, jusqu'à `month` compris."""
        m = checked_month(host, month)
        with engine.connect() as conn:
            return budget_app.budget_months(conn, m, months)

    @r.get("/flows")
    def flows(
        p: AnyReader,
        month: Annotated[str | None, Query(pattern=MONTH)] = None,
        period: Annotated[str, Query(pattern=PERIOD)] = "m",
    ) -> dict[str, Any]:
        """Revenus → groupes (fixe, variable, épargne) → catégories, et le reste sur compte.
        `period=q` : les trois mois complets avant `month`, comme le budget."""
        m = checked_month(host, month)
        with engine.connect() as conn:
            return budget_app.flows(conn, m, aggregates_only=aggregates_only(p), period=period)

    @r.get("/trend")
    def trend(
        _p: AnyReader,
        category: str | None = None,
        months: Annotated[int, Query(ge=1, le=36)] = 12,
        month: Annotated[str | None, Query(pattern=MONTH)] = None,
    ) -> dict[str, Any]:
        with engine.connect() as conn:
            series = totals.trend(conn, category, months, month or this_month(host))
        return {"category": category, "series": series}

    @r.get("/review")
    def review(_p: Reader) -> dict[str, Any]:
        """Écritures sans catégorie, groupées par contrepartie normalisée."""
        with engine.connect() as conn:
            return {"groups": reviewing.review(conn)}

    @r.get("/alerts")
    def alerts(_p: Reader) -> dict[str, Any]:
        """Alertes des sentinelles des 31 derniers jours (budget, abonnements, 3a)."""
        with engine.connect() as conn:
            return {"items": sentinels.recent(conn, host.today())}

    @r.get("/rules/packs")
    def rule_packs(_p: Reader) -> dict[str, Any]:
        """Packs de règles livrés, version installée, ceux du pays de l'instance, et le nombre
        de règles actives hors système (parcours d'accueil)."""
        country = profile.load(host.settings).country
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

    @r.get("/recurring")
    def recurring_route(p: AnyReader) -> dict[str, Any]:
        """Abonnements et paiements réguliers, prochaines échéances, total mensuel ; pour la
        portée `aggregates`, les totaux seulement."""
        host.refresh_snapshots()
        with engine.connect() as conn:
            return recurring.listing(conn, host.today(), aggregates_only=aggregates_only(p))

    return r
