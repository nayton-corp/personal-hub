"""Outils de l'assistant pour le patrimoine (lot 7) : comptes et leur valeur, patrimoine net.
Règles communes : registre/interface/tools.py."""

from __future__ import annotations

from typing import Any, Protocol

from hub.core.domain import McpTool, ToolCaller
from hub.domains.finance.patrimoine.app import account_list, holdings
from hub.domains.finance.registre.interface import http
from hub.domains.finance.registre.interface.tools import (
    AGGREGATES,
    NONE,
    NoArgs,
    ToolBox,
    amount,
    tool,
)
from hub.domains.finance.registre.model import period


class Host(http.Host, Protocol):
    def pillar3a(self) -> dict[str, Any]: ...


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

    def tools(self, category: dict[str, Any]) -> list[McpTool]:
        """Les outils de ce sous-contexte ; `category` : le schéma de la liste fermée."""
        return [
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
