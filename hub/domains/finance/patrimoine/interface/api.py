"""Routes du patrimoine : comptes et leur valeur, chiffres clés, positions, dettes, transparence
des fonds, virements appariés, historique et performance."""

from __future__ import annotations

from typing import Annotated, Any, Protocol

from fastapi import APIRouter, Query

from hub.core.errors import Problem
from hub.domains.finance.patrimoine.app import (
    account_list,
    debts,
    lookthrough,
    perf_lines,
    performance,
    snapshots,
    transfers,
)
from hub.domains.finance.patrimoine.app import holdings as positions
from hub.domains.finance.registre.interface import http
from hub.domains.finance.registre.interface.http import (
    DATE,
    MONTH,
    AnyReader,
    aggregates_only,
    checked_month,
)
from hub.kernel.money import base_currency

DIMENSION = r"^(region|sector|currency|holding)$"


class Host(http.Host, Protocol):
    def pillar3a(self) -> dict[str, Any]: ...

    def refresh_snapshots(self) -> object: ...


def build_router(host: Host) -> APIRouter:
    r = APIRouter()
    engine = host.engine()

    @r.get("/accounts")
    def accounts(_p: AnyReader) -> dict[str, Any]:
        """Comptes, IBAN masqué, solde calculé, dernier CLBD et écart."""
        with engine.connect() as conn:
            return {"items": account_list.accounts(conn)}

    @r.get("/kpis")
    def kpis(
        _p: AnyReader, month: Annotated[str | None, Query(pattern=MONTH)] = None
    ) -> dict[str, Any]:
        """Chiffres clés de l'accueil : patrimoine et variations, mois, liquidités, à traiter."""
        m = checked_month(host, month)
        with engine.connect() as conn:
            return positions.kpis(conn, m, host.today(), **host.pillar3a())

    @r.get("/holdings")
    def holdings(
        _p: AnyReader, on: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}-\d{2}$")] = None
    ) -> dict[str, Any]:
        """Positions des comptes de titres (VIAC) à une date, aujourd'hui par défaut."""
        with engine.connect() as conn:
            return positions.holdings(conn, on or host.today().isoformat())

    @r.get("/debts")
    def debts_route(_p: AnyReader) -> dict[str, Any]:
        """Dettes et leur solde aujourd'hui : départ, paiements et intérêts depuis, fin projetée."""
        with engine.connect() as conn:
            return {"items": debts.items(conn, host.today().isoformat())}

    @r.get("/lookthrough")
    def lookthrough_route(
        _p: AnyReader,
        dimension: Annotated[str, Query(pattern=DIMENSION)] = "region",
        on: Annotated[str | None, Query(pattern=DATE)] = None,
    ) -> dict[str, Any]:
        """Positions ventilées par région, secteur, devise, ou les dix plus grosses lignes
        sous-jacentes (transparence des fonds)."""
        with engine.connect() as conn:
            return lookthrough.breakdown(conn, dimension, on or host.today().isoformat())

    @r.get("/transfers")
    def transfers_route(p: AnyReader) -> dict[str, Any]:
        """Virements appariés par méthode et virements sans autre côté."""
        host.refresh_snapshots()
        with engine.connect() as conn:
            return transfers.summary(conn, detailed=not aggregates_only(p))

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
            dates = snapshots.steps(from_, to or host.today().isoformat(), step)
            if not dates or len(dates) > snapshots.MAX_LIVE_POINTS:
                raise Problem("validation.params", "période vide ou trop longue pour ce pas")
            with engine.connect() as conn:
                return snapshots.live_history(conn, dates)
        host.refresh_snapshots()
        with engine.connect() as conn:
            return snapshots.history(conn, from_, to)

    @r.get("/performance")
    def performance_route(
        _p: AnyReader,
        from_: Annotated[str | None, Query(alias="from", pattern=DATE)] = None,
        to: Annotated[str | None, Query(pattern=DATE)] = None,
        step: Annotated[str, Query(pattern=r"^(day|week|month)$")] = "week",
        line: Annotated[list[str] | None, Query(max_length=300)] = None,
    ) -> dict[str, Any]:
        """Performance d'une sélection de lignes (`line=<compte>|<instrument>`, `<compte>|cash`,
        `debt:<id>` ; par défaut, celles de l'app) : courbe de la valeur, des apports nets, du
        gain et du rendement pondéré dans le temps ; résumé (gain, revenus, frais, rendement,
        rendement personnel annuel) ; le même par compte, par actif, par ligne ; par mois et par
        année ; risque. Des agrégats seulement."""
        if line is not None and len(line) > 500:
            raise Problem("validation.params", "trop de lignes")
        with engine.connect() as conn:
            eng = perf_lines.engine_for(conn, host.today().isoformat())
        if eng is None:
            return performance.empty(base_currency())
        return performance.report(eng, line, from_, to, step)

    return r
