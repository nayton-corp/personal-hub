"""Routes du patrimoine : comptes et leur valeur, chiffres clés, positions, dettes, transparence
des fonds, virements appariés, historique, performance et cours d'un instrument."""

from __future__ import annotations

from typing import Annotated, Any, Protocol

from fastapi import APIRouter, BackgroundTasks, Query

from hub.core.errors import Problem
from hub.domains.finance.packs import CountryPack
from hub.domains.finance.patrimoine.app import (
    account_list,
    allocation,
    debts,
    fees,
    goods,
    perf_lines,
    performance,
    price_history,
    reconcile,
    snapshots,
    strategies,
    transfers,
)
from hub.domains.finance.patrimoine.app import holdings as positions
from hub.domains.finance.patrimoine.interface.goods_schemas import FeesOut, GoodListOut
from hub.domains.finance.patrimoine.interface.schemas import (
    AccountListOut,
    BreaksOut,
    DebtListOut,
    HoldingsOut,
    KpisOut,
    LookthroughOut,
    NetworthHistoryOut,
    PerformanceOut,
    PricesOut,
    TransfersOut,
)
from hub.domains.finance.patrimoine.interface.strategy_schemas import StrategiesOut
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

    def pack(self) -> CountryPack: ...

    def refresh_snapshots(self) -> object: ...


def build_router(host: Host) -> APIRouter:
    r = APIRouter()
    engine = host.engine()

    @r.get("/accounts", response_model=AccountListOut)
    def accounts(_p: AnyReader) -> dict[str, Any]:
        """Comptes, IBAN masqué, solde calculé, dernier CLBD et écart."""
        with engine.connect() as conn:
            return {"items": account_list.accounts(conn)}

    @r.get("/kpis", response_model=KpisOut)
    def kpis(
        _p: AnyReader, month: Annotated[str | None, Query(pattern=MONTH)] = None
    ) -> dict[str, Any]:
        """Chiffres clés de l'accueil : patrimoine et variations, mois, liquidités, à traiter."""
        m = checked_month(host, month)
        with engine.connect() as conn:
            return positions.kpis(conn, m, host.today(), **host.pillar3a())

    @r.get("/holdings", response_model=HoldingsOut)
    def holdings(
        _p: AnyReader, on: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}-\d{2}$")] = None
    ) -> dict[str, Any]:
        """Positions des comptes de titres (VIAC) à une date, aujourd'hui par défaut."""
        with engine.connect() as conn:
            return positions.holdings(conn, on or host.today().isoformat())

    @r.get("/debts", response_model=DebtListOut)
    def debts_route(_p: AnyReader) -> dict[str, Any]:
        """Dettes et leur solde aujourd'hui : départ, paiements et intérêts depuis, fin projetée."""
        with engine.connect() as conn:
            return {"items": debts.items(conn, host.today().isoformat())}

    @r.get("/goods", response_model=GoodListOut)
    def goods_route(_p: AnyReader) -> dict[str, object]:
        """Biens hors comptes (logement, véhicule, objet, prêt accordé) et leur valeur
        aujourd'hui : la dernière valeur saisie, suivie de la variation annuelle du bien.
        Écrire : `save_good` (Double Sas)."""
        with engine.connect() as conn:
            return {"items": goods.items(conn, host.today().isoformat())}

    @r.get("/fees", response_model=FeesOut)
    def fees_route(_p: AnyReader) -> dict[str, object]:
        """Frais courants des fonds détenus : TER, coût par an et sur trente ans (ordre de
        grandeur, au rendement supposé `assumed_return_pct`). Un fonds sans TER connu a
        `ter_pct` nul et reste hors des totaux. Saisir un TER : `set_fund_fee` (Double Sas)."""
        with engine.connect() as conn:
            return fees.summary(conn, host.today().isoformat())

    @r.get("/strategies", response_model=StrategiesOut)
    def strategies_route(_p: AnyReader) -> dict[str, object]:
        """Les stratégies (vendre par paliers, achat régulier, acheter une grosse baisse) : la
        phrase, où on en est aujourd'hui, l'étape atteinte qui attend une réponse, les étapes
        passées ; et `scopes`, sur quoi une stratégie peut porter. Le hub ne passe aucun ordre.
        Écrire : `save_strategy` ; répondre à une étape : `answer_strategy_step` (Double Sas)."""
        today = host.today()
        with engine.connect() as conn:
            return {
                "items": strategies.items(conn, today),
                "scopes": strategies.scopes(conn, today),
            }

    @r.get("/breaks", response_model=BreaksOut)
    def breaks_route(_p: AnyReader) -> dict[str, Any]:
        """Rapprochement d'aujourd'hui : les ruptures ouvertes (compte, actif, parts, valeur,
        cause, gestes), leur total et la part des placements expliquée et cotée. Une rupture
        se règle par la proposition `decide_break` (Double Sas)."""
        with engine.connect() as conn:
            return reconcile.summary(conn, host.today().isoformat())

    @r.get("/lookthrough", response_model=LookthroughOut)
    def lookthrough_route(
        _p: AnyReader,
        dimension: Annotated[str, Query(pattern=DIMENSION)] = "region",
        on: Annotated[str | None, Query(pattern=DATE)] = None,
        line: Annotated[list[str] | None, Query(max_length=300)] = None,
    ) -> dict[str, Any]:
        """Le patrimoine réparti par région, secteur ou devise, liquidités comprises, ou les dix
        plus grosses lignes sous-jacentes des fonds. `line` : la sélection de l'écran, comme
        pour `/performance` (par défaut, les lignes de l'app). La somme des cases (`total`),
        dettes à part (`owed`), est la valeur de la sélection. Des agrégats seulement."""
        with engine.connect() as conn:
            return allocation.breakdown(
                conn, dimension, on or host.today().isoformat(), host.pack(), line
            )

    @r.get("/transfers", response_model=TransfersOut, response_model_exclude_unset=True)
    def transfers_route(p: AnyReader, background: BackgroundTasks) -> dict[str, Any]:
        """Virements appariés par méthode et virements sans autre côté. Une lecture n'écrit
        pas : les instantanés se rafraîchissent après la réponse, en tâche de fond."""
        background.add_task(host.refresh_snapshots)
        with engine.connect() as conn:
            return transfers.summary(conn, detailed=not aggregates_only(p))

    @r.get("/networth/history", response_model=NetworthHistoryOut)
    def networth_history(
        _p: AnyReader,
        background: BackgroundTasks,
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
        background.add_task(host.refresh_snapshots)  # après la réponse, jamais dans la lecture
        with engine.connect() as conn:
            return snapshots.history(conn, from_, to)

    @r.get("/performance", response_model=PerformanceOut)
    def performance_route(
        _p: AnyReader,
        from_: Annotated[str | None, Query(alias="from", pattern=DATE)] = None,
        to: Annotated[str | None, Query(pattern=DATE)] = None,
        step: Annotated[str, Query(pattern=r"^(day|week|month)$")] = "week",
        line: Annotated[list[str] | None, Query(max_length=300)] = None,
        account: Annotated[list[str] | None, Query(max_length=300)] = None,
    ) -> dict[str, Any]:
        """Performance d'une sélection (`account=<compte>` : toutes ses lignes, celles d'une
        position vendue depuis comprises ; `line=<compte>|<instrument>`, `<compte>|cash`,
        `debt:<id>` ; par défaut, les lignes de l'app) : courbe de la valeur, des apports nets, du
        gain et du rendement pondéré dans le temps ; résumé (gain, revenus, frais, rendement,
        rendement personnel annuel) ; le même par compte, par actif, par ligne ; par mois et par
        année ; risque. Les points tombent sur le calendrier (chaque jour, chaque dimanche, chaque
        fin de mois) ; au-delà de 400, le pas s'élargit. `extremes` : le plus haut et le plus bas
        de tous les jours de la période. Des agrégats seulement."""
        with engine.connect() as conn:
            eng = perf_lines.engine_for(conn, host.today().isoformat())
        if eng is None:
            return performance.empty(base_currency())
        if account:
            line = sorted({*(line or []), *eng.account_lines(account)})
            if not line:  # un compte inconnu n'est pas « tout le patrimoine »
                return performance.empty(base_currency())
        return performance.report(eng, line, from_, to, step)

    @r.get("/prices", response_model=PricesOut)
    def prices_route(
        _p: AnyReader,
        isin: Annotated[str, Query(min_length=3, max_length=40)],
        from_: Annotated[str | None, Query(alias="from", pattern=DATE)] = None,
        to: Annotated[str | None, Query(pattern=DATE)] = None,
    ) -> dict[str, Any]:
        """Cours connus d'un instrument entre deux dates, dans sa devise de cotation, au plus
        400 points : la courbe « Cours » de la page d'un actif."""
        with engine.connect() as conn:
            return price_history.history(conn, isin, from_, to or host.today().isoformat())

    return r
