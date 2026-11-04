"""Outils de lecture du classement à parité avec ses routes (audit M11) : flux du mois, totaux
mois par mois, packs de règles. Règles communes : registre/interface/tools.py."""

from __future__ import annotations

from typing import Any, Protocol

from pydantic import Field

from hub.core import profile
from hub.core.domain import McpTool, ToolCaller
from hub.domains.finance.classement.app import budget, packs, rules
from hub.domains.finance.registre.interface import http
from hub.domains.finance.registre.interface.tools import (
    AGGREGATES,
    MONTH_PROP,
    NONE,
    Month,
    NoArgs,
    ToolBox,
    _Args,
    _obj,
    text_out,
    tool,
)
from hub.platform.settings import Settings


class Host(http.Host, Protocol):
    settings: Settings


class FlowsArgs(_Args):
    month: Month = None
    period: str = Field(default="m", pattern=r"^[mq]$")


class MonthsArgs(_Args):
    month: Month = None
    months: int = Field(default=6, ge=1, le=36)


class ClassementReads(ToolBox):
    host: Host

    def flows(self, a: FlowsArgs, caller: ToolCaller) -> dict[str, Any]:
        month = self._month(a.month)
        with self.engine.connect() as conn:
            out = budget.flows(
                conn, month, aggregates_only=self._aggregates_only(caller), period=a.period
            )
            return self._wrap(conn, text_out(out))

    def budget_months(self, a: MonthsArgs, caller: ToolCaller) -> dict[str, Any]:
        month = self._month(a.month)
        with self.engine.connect() as conn:
            return self._wrap(conn, text_out(budget.budget_months(conn, month, a.months)))

    def rule_packs(self, _a: NoArgs, caller: ToolCaller) -> dict[str, Any]:
        country = profile.load(self.host.settings).country
        with self.engine.connect() as conn:
            done = packs.installed(conn)
            active = sum(
                1
                for x in rules.list_rules(conn)
                if x.active and not x.id.startswith(rules.SYSTEM_PREFIX)
            )
            items = [
                {
                    "name": p.name,
                    "label": p.label,
                    "country": p.country,
                    "version": p.version,
                    "installed": done.get(p.name),
                    "rules": len(p.specs()),
                }
                for p in packs.available().values()
            ]
            return self._wrap(
                conn,
                {
                    "packs": items,
                    "suggested": [p.name for p in packs.defaults_for(country)],
                    "active_rules": active,
                },
            )

    def tools(self, category: dict[str, Any]) -> list[McpTool]:
        return [
            tool(
                "finance_flows",
                "Les flux d'un mois : revenus par source, puis fixe, variable, épargne par "
                "catégorie, et le reste sur compte ; `period: q` pour le trimestre.",
                _obj({"month": MONTH_PROP, "period": {"type": "string", "enum": ["m", "q"]}}),
                AGGREGATES,
                FlowsArgs,
                self.flows,
            ),
            tool(
                "finance_budget_months",
                "Revenus, dépenses fixes et variables, épargne, placements et taux d'épargne, "
                "mois par mois jusqu'au mois demandé.",
                _obj(
                    {
                        "month": MONTH_PROP,
                        "months": {"type": "integer", "minimum": 1, "maximum": 36},
                    }
                ),
                AGGREGATES,
                MonthsArgs,
                self.budget_months,
            ),
            tool(
                "finance_rule_packs",
                "Packs de règles livrés, version installée, ceux du pays, et le nombre de règles "
                "actives (`finance_propose_install_pack` en installe un).",
                NONE,
                AGGREGATES,
                NoArgs,
                self.rule_packs,
            ),
        ]
