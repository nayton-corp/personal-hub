"""Outils de l'assistant pour le patrimoine (lot 7, puis la parité avec les routes, audit M11) :
comptes et leur valeur, patrimoine net et son historique, positions, dettes, ruptures du
rapprochement, performance, transparence des fonds, virements, cours d'un actif. Règles
communes : registre/interface/tools.py."""

from __future__ import annotations

from typing import Annotated, Any, Protocol

from pydantic import Field

from hub.core.domain import McpTool, ToolCaller
from hub.domains.finance.packs.base import CountryPack
from hub.domains.finance.patrimoine.app import (
    account_list,
    allocation,
    debts,
    holdings,
    perf_lines,
    performance,
    price_history,
    reconcile,
    snapshots,
    strategies,
    transfers,
)
from hub.domains.finance.registre.interface import http
from hub.domains.finance.registre.interface.tools import (
    AGGREGATES,
    NONE,
    NoArgs,
    ToolBox,
    _Args,
    _obj,
    amount,
    text_out,
    tool,
)
from hub.domains.finance.registre.model import period
from hub.kernel.money import base_currency

DATE = r"^\d{4}-\d{2}-\d{2}$"
Day = Annotated[str | None, Field(default=None, pattern=DATE)]
DAY_PROP = {"type": "string", "pattern": DATE, "description": "Jour AAAA-MM-JJ."}


class OnArgs(_Args):
    on: Day = None


class RangeArgs(_Args):
    from_: Day = Field(default=None, alias="from")
    to: Day = None


class PerformanceArgs(RangeArgs):
    step: str = Field(default="month", pattern=r"^(week|month)$")


class LookthroughArgs(_Args):
    dimension: str = Field(default="region", pattern=r"^(region|sector|currency|holding)$")


class PricesArgs(RangeArgs):
    isin: str = Field(min_length=3, max_length=40)


class Host(http.Host, Protocol):
    def pillar3a(self) -> dict[str, Any]: ...

    def pack(self) -> CountryPack: ...


class PatrimoineTools(ToolBox):
    host: Host

    def list_accounts(self, _a: NoArgs, caller: ToolCaller) -> dict[str, Any]:
        with self.engine.connect() as conn:
            items = [
                {
                    "id": a["id"],
                    "institution": a["institution"],
                    "name": a["name"],
                    "kind": a["kind"],
                    "balance": amount(a["balance"]),
                    "value": amount(a["value"]),
                    "last_booking": a["last_booking"],
                    "last_statement": (a["last_clbd"] or {}).get("on_date"),
                }
                for a in account_list.accounts(conn)
            ]
            return self._wrap(conn, {"accounts": items})

    def networth(self, _a: NoArgs, caller: ToolCaller) -> dict[str, Any]:
        today = self.host.today()
        with self.engine.connect() as conn:
            month = period.month_of(today)
            k = holdings.kpis(conn, month, today, **self.host.pillar3a())
            p3 = k["pillar3a"]
            return self._wrap(
                conn,
                {
                    "as_of": k["as_of"],
                    "net_worth": amount(k["net_worth"]),
                    "by_envelope": {e: amount(v) for e, v in k["envelopes"].items()},
                    "liquid": amount(k["liquid"]),
                    "change_1m": amount(k["change_1m"]["amount"]),
                    "change_ytd": amount(k["change_ytd"]["amount"]),
                    "deposits_ytd": amount(k["deposits_ytd"]),
                    "market_ytd": amount(k["market_ytd"]),
                    "pillar3a": p3
                    and {
                        "year": p3["year"],
                        "cap": amount(p3["cap"]),
                        "paid": amount(p3["paid"]),
                        "margin": amount(p3["margin"]),
                    },
                    "missing_prices": k["missing_prices"],
                },
            )

    def breaks(self, _a: NoArgs, caller: ToolCaller) -> dict[str, Any]:
        with self.engine.connect() as conn:
            out = reconcile.summary(conn, self.host.today().isoformat())
            return self._wrap(conn, text_out(out))

    def debts_list(self, _a: NoArgs, caller: ToolCaller) -> dict[str, Any]:
        with self.engine.connect() as conn:
            return self._wrap(
                conn, {"debts": text_out(debts.items(conn, self.host.today().isoformat()))}
            )

    def strategies_list(self, _a: NoArgs, caller: ToolCaller) -> dict[str, object]:
        with self.engine.connect() as conn:
            found = strategies.items(conn, self.host.today())
            return self._wrap(conn, {"strategies": text_out(found)})

    def holdings_list(self, a: OnArgs, caller: ToolCaller) -> dict[str, Any]:
        with self.engine.connect() as conn:
            out = holdings.holdings(conn, a.on or self.host.today().isoformat())
            return self._wrap(conn, text_out(out))

    def performance_report(self, a: PerformanceArgs, caller: ToolCaller) -> dict[str, Any]:
        with self.engine.connect() as conn:
            eng = perf_lines.engine_for(conn, self.host.today().isoformat())
            if eng is None:
                return self._wrap(conn, text_out(performance.empty(base_currency())))
            out = performance.report(eng, None, a.from_, a.to, a.step)
            out.pop("items", None)  # la courbe point par point : pour l'app, pas pour un modèle
            out.pop("by_line", None)
            return self._wrap(conn, text_out(out))

    def lookthrough_report(self, a: LookthroughArgs, caller: ToolCaller) -> dict[str, Any]:
        with self.engine.connect() as conn:
            out = allocation.breakdown(
                conn, a.dimension, self.host.today().isoformat(), self.host.pack()
            )
            return self._wrap(conn, text_out(out))

    def transfers_report(self, _a: NoArgs, caller: ToolCaller) -> dict[str, Any]:
        with self.engine.connect() as conn:
            out = transfers.summary(conn, detailed=not self._aggregates_only(caller))
            return self._wrap(conn, text_out(out))

    def prices(self, a: PricesArgs, caller: ToolCaller) -> dict[str, Any]:
        with self.engine.connect() as conn:
            out = price_history.history(
                conn, a.isin, a.from_, a.to or self.host.today().isoformat()
            )
            return self._wrap(conn, text_out(out))

    def networth_history(self, a: RangeArgs, caller: ToolCaller) -> dict[str, Any]:
        with self.engine.connect() as conn:
            out = snapshots.history(conn, a.from_, a.to)
            for point in out.get("items", []):
                point.pop("by_account", None)  # des identifiants de comptes : l'app seulement
            return self._wrap(conn, text_out(out))

    def tools(self, category: dict[str, Any]) -> list[McpTool]:
        """Les outils de ce sous-contexte ; `category` : le schéma de la liste fermée."""
        range_props = {"from": DAY_PROP, "to": DAY_PROP}
        return [
            tool(
                "finance_breaks",
                "Rapprochement d'aujourd'hui : les soldes non expliqués (compte, actif, parts, "
                "valeur, cause, gestes possibles), leur total, la part des placements expliquée.",
                NONE,
                AGGREGATES,
                NoArgs,
                self.breaks,
            ),
            tool(
                "finance_debts",
                "Dettes et leur solde aujourd'hui : départ, paiements et intérêts depuis, "
                "mensualité habituelle, fin projetée.",
                NONE,
                AGGREGATES,
                NoArgs,
                self.debts_list,
            ),
            tool(
                "finance_strategies",
                "Les stratégies écrites (vendre par paliers, achat régulier, acheter une grosse "
                "baisse) : la phrase, où on en est aujourd'hui, l'étape qui attend une réponse. "
                "Le hub ne passe aucun ordre, il prévient.",
                NONE,
                AGGREGATES,
                NoArgs,
                self.strategies_list,
            ),
            tool(
                "finance_holdings",
                "Positions des comptes de titres et des cryptos à une date (aujourd'hui par "
                "défaut) : parts, cours, valeur, prix de revient, gain, et le résultat crypto.",
                _obj({"on": DAY_PROP}),
                AGGREGATES,
                OnArgs,
                self.holdings_list,
            ),
            tool(
                "finance_performance",
                "Performance des placements entre deux dates : gain, apports nets, rendement "
                "pondéré dans le temps, revenus, frais, par compte et par actif, par mois et par "
                "année, risque, et les événements de la courbe.",
                _obj({**range_props, "step": {"type": "string", "enum": ["week", "month"]}}),
                AGGREGATES,
                PerformanceArgs,
                self.performance_report,
            ),
            tool(
                "finance_lookthrough",
                "Le patrimoine réparti par région, secteur ou devise, liquidités comprises (part "
                "sûre, estimée, non répartie, inconnue), ou les plus grosses lignes sous-jacentes "
                "des fonds.",
                _obj(
                    {
                        "dimension": {
                            "type": "string",
                            "enum": ["region", "sector", "currency", "holding"],
                        }
                    }
                ),
                AGGREGATES,
                LookthroughArgs,
                self.lookthrough_report,
            ),
            tool(
                "finance_transfers",
                "Virements appariés entre mes comptes, par méthode, et le nombre de virements "
                "sans autre côté (leur liste avec la lecture complète).",
                NONE,
                AGGREGATES,
                NoArgs,
                self.transfers_report,
            ),
            tool(
                "finance_prices",
                "Cours connus d'un actif (ISIN ou symbole) entre deux dates, dans sa devise.",
                _obj({"isin": {"type": "string"}, **range_props}, ["isin"]),
                AGGREGATES,
                PricesArgs,
                self.prices,
            ),
            tool(
                "finance_networth_history",
                "Le patrimoine mois par mois : valeur, versements cumulés, valeur par enveloppe.",
                _obj(range_props),
                AGGREGATES,
                RangeArgs,
                self.networth_history,
            ),
            tool(
                "finance_list_accounts",
                "Comptes, solde calculé et valeur (titres au dernier cours), date du dernier "
                "relevé. Aucun IBAN.",
                NONE,
                AGGREGATES,
                NoArgs,
                self.list_accounts,
            ),
            tool(
                "finance_networth",
                "Patrimoine net dans la devise de base, répartition par enveloppe, variations "
                "sur un mois et depuis janvier, marge 3a de l'année.",
                NONE,
                AGGREGATES,
                NoArgs,
                self.networth,
            ),
        ]
