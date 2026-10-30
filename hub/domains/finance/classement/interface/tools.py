"""Outils de l'assistant pour le classement et le budget (lot 7, puis la catégorisation par
lot) : totaux du mois, budget, tendance d'une catégorie, abonnements, file « À classer », et les
propositions de catégorie, de règle et de budget. Règles communes : registre/interface/tools.py.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Protocol

from sqlalchemy import Connection, text

from hub.core.domain import McpTool, ToolCaller
from hub.core.errors import Problem
from hub.domains.finance.classement.app import (
    budget,
    insights,
    recurring,
    review,
    sentinels,
    totals,
)
from hub.domains.finance.classement.app.categorize_kinds import ENTRIES_MAX
from hub.domains.finance.classement.interface.tool_args import (
    REVIEW_GROUPS,
    REVIEW_IDS,
    REVIEW_OFFSET_MAX,
    RULE_PRIORITY,
    ProposeBudgetArgs,
    ProposeCategoriesArgs,
    ProposeCategoryArgs,
    ProposeRuleArgs,
    ReviewArgs,
    TrendArgs,
)
from hub.domains.finance.registre.interface import http
from hub.domains.finance.registre.interface.tools import (
    AGGREGATES,
    ENTRY_PROP,
    EXTERNAL_NOTICE,
    MONTH_PROP,
    NONE,
    PROPOSE,
    READ,
    REASON_PROP,
    MonthArgs,
    NoArgs,
    ToolBox,
    _obj,
    amount,
    base_text,
    tool,
)
from hub.domains.finance.registre.model import amounts
from hub.domains.finance.registre.model.amounts import MIN_COUNT_FOR_AGGREGATES
from hub.kernel.money import Money, base_currency
from hub.kernel.text import normalize


class Host(http.Host, Protocol):
    def refresh_snapshots(self) -> object: ...


class ClassementTools(ToolBox):
    host: Host

    def month_summary(self, a: MonthArgs, caller: ToolCaller) -> dict[str, Any]:
        month = self._month(a.month)
        with self.engine.connect() as conn:
            s = totals.summary(conn, month, aggregates_only=self._aggregates_only(caller))
            names = insights.category_names(conn)
            by_category = [
                {
                    "category": x["category"],
                    "name": names.get(x["category"], x["category"]),
                    "group": x["group"],
                    # dépense en positif, revenu en positif : ce qu'on répond à « combien »
                    "amount": base_text(abs(int(x["total"]["minor"]))),
                    "direction": "credit" if x["total"]["minor"] > 0 else "debit",
                    "count": x["count"],
                }
                for x in s["by_category"]
            ]
            by_category.sort(key=lambda x: (x["direction"], -Decimal(x["amount"])))
            return self._wrap(
                conn,
                {
                    "month": month,
                    "complete": amounts.month_end(month) < self.host.today(),
                    "income": amount(s["income"]),
                    "expenses": amount(s["expenses"]),
                    "savings": base_text(int(s["income"]["minor"]) - int(s["expenses"]["minor"])),
                    "uncategorized": amount(s["uncategorized"]),
                    "by_category": by_category,
                },
            )

    def budget_status(self, a: MonthArgs, caller: ToolCaller) -> dict[str, Any]:
        month = self._month(a.month)
        today = self.host.today()
        with self.engine.connect() as conn:
            b = budget.budget(
                conn, month, "m", today, aggregates_only=self._aggregates_only(caller)
            )
            projected = {p.category: p for p in sentinels.budget_projection(conn, month, today)}
            lines = []
            for x in b["lines"]:
                line = {
                    "category": x["category"],
                    "name": x.get("name", x["category"]),
                    "spent": amount(x["spent"]),
                    "target": amount(x["target"]) if x.get("target") else None,
                    "over": bool(x.get("over")),
                }
                p = projected.get(x["category"])
                if p is not None:
                    line["projected"] = base_text(p.projected)
                    line["likely_over"] = p.likely_over
                lines.append(line)
            return self._wrap(
                conn,
                {
                    "month": month,
                    "budget": amount(b["budget"]) if b["budget"] else None,
                    "expenses": amount(b["expenses"]),
                    "rest_to_live": amount(b["rest_to_live"]) if b["rest_to_live"] else None,
                    "days_left": b["days_left"],
                    "over": [x["name"] for x in lines if x["over"]],
                    "lines": lines,
                },
            )

    def category_trend(self, a: TrendArgs, caller: ToolCaller) -> dict[str, Any]:
        month = self._month(None)
        aggregates_only = self._aggregates_only(caller)
        with self.engine.connect() as conn:
            cat = self._category(conn, a.category)
            series = []
            for x in totals.trend(conn, a.category, a.months, month):
                count = int(x["count"])
                hidden = aggregates_only and 0 < count < MIN_COUNT_FOR_AGGREGATES
                series.append(
                    {
                        "month": x["month"],
                        # montant positif ; un mois de 1 ou 2 écritures reste masqué en agrégats
                        "amount": None if hidden else base_text(abs(int(x["total"]["minor"]))),
                        "count": count,
                    }
                )
            return self._wrap(conn, {"category": cat["id"], "name": cat["name"], "series": series})

    def recurring_list(self, _a: NoArgs, caller: ToolCaller) -> dict[str, Any]:
        self.host.refresh_snapshots()
        today = self.host.today()
        with self.engine.connect() as conn:
            r = recurring.listing(conn, today, aggregates_only=False)
            items = [
                {
                    "counterparty": i["label"],
                    "category": i["category"],
                    "cadence": i["cadence"],
                    "amount": base_text(abs(int(i["amount"]["minor"])))
                    if i["amount"]["currency"] == base_currency()
                    else amount(i["amount"]),
                    "monthly": amount(i["monthly"]),
                    "next_date": i["next_date"],
                }
                for i in r.get("items", [])
                if i["active"]
            ]
            return self._wrap(
                conn,
                {
                    "count": r["count"],
                    "monthly_total": [amount(m) for m in r["monthly_total"]],
                    "items": items,
                    "external_text": EXTERNAL_NOTICE,
                },
            )

    def known_merchants(self, conn: Connection) -> set[str]:
        """Groupes d'« À classer » (commerçant ou contrepartie) qui ont déjà au moins une écriture
        catégorisée, hors règle « tout le reste »."""
        rows = conn.execute(
            text(
                "SELECT DISTINCT e.counterparty, e.label FROM entries e "  # noqa: S608
                "JOIN v_entry_category vc ON vc.entry_seq = e.seq "
                "LEFT JOIN categorizations c ON c.seq = vc.categorization_seq "
                "LEFT JOIN rules r ON r.id = c.rule_id "
                f"WHERE vc.category_id IS NOT NULL AND e.kind = 'movement' "
                f"AND NOT coalesce({review.CATCH_ALL}, 0)"
            )
        )
        return {review.review_key(cp, label) for cp, label in rows}

    def to_review(self, a: ReviewArgs, caller: ToolCaller) -> dict[str, Any]:
        with self.engine.connect() as conn:
            known = self.known_merchants(conn)
            groups = [
                {
                    "counterparty": g["counterparty"],
                    "count": g["count"],
                    "total": amount(g["total"]),
                    "direction": g["direction"],
                    "known_merchant": g["counterparty"] in known,
                    "guess": g["guess"],
                    "entry_ids": g["entry_ids"][:REVIEW_IDS],
                }
                for g in review.review(conn, a.offset + a.limit)[a.offset :]
            ]
            return self._wrap(
                conn,
                {
                    "groups": groups,
                    "to_categorize": insights.to_categorize(conn),
                    "external_text": EXTERNAL_NOTICE,
                },
            )

    def propose_category(self, a: ProposeCategoryArgs, caller: ToolCaller) -> dict[str, Any]:
        with self.engine.connect() as conn:
            self._category(conn, a.category)
        return caller.propose(
            "recategorize",
            {"entry_id": a.entry_id, "category_id": a.category, "suggested": True},
            a.reason,
        )

    def propose_categories(self, a: ProposeCategoriesArgs, caller: ToolCaller) -> dict[str, Any]:
        with self.engine.connect() as conn:
            self._category(conn, a.category)
        return caller.propose(
            "categorize_entries",
            {"entry_ids": a.entry_ids, "category_id": a.category, "suggested": True},
            a.reason,
        )

    def propose_rule(self, a: ProposeRuleArgs, caller: ToolCaller) -> dict[str, Any]:
        with self.engine.connect() as conn:
            self._category(conn, a.category)
        pattern = normalize(a.keyword)
        if len(pattern) < 3:
            raise Problem("validation.params", "mot-clé trop court")
        return caller.propose(
            "create_rule",
            {
                "field": "search_text",
                "pattern": pattern,
                "direction": a.direction,
                "category_id": a.category,
                "priority": RULE_PRIORITY,
            },
            a.reason,
        )

    def propose_budget(self, a: ProposeBudgetArgs, caller: ToolCaller) -> dict[str, Any]:
        with self.engine.connect() as conn:
            cat = self._category(conn, a.category)
        if cat["group"] not in insights.EXPENSE_GROUPS:
            raise Problem("validation.params", "budget : catégorie de dépense seulement")
        minor = Money.from_decimal(a.amount, base_currency()).minor
        if a.cadence == "year":
            minor = (minor + 6) // 12  # cible mensuelle stockée, arrondie au centime
        return caller.propose(
            "set_budget",
            {"category_id": a.category, "monthly_minor": minor, "cadence": a.cadence},
            a.reason,
        )

    def tools(self, category: dict[str, Any]) -> list[McpTool]:
        """Les outils de ce sous-contexte ; `category` : le schéma de la liste fermée."""
        return [
            tool(
                "finance_month_summary",
                "Totaux d'un mois : revenus, dépenses, épargne, et montant par catégorie (en "
                "positif). Répond à « combien en restaurants ce mois ? ».",
                _obj({"month": MONTH_PROP}),
                AGGREGATES,
                MonthArgs,
                self.month_summary,
            ),
            tool(
                "finance_budget_status",
                "Budget d'un mois : dépensé contre cible par catégorie, projection à fin de "
                "mois, dépassements, reste à vivre.",
                _obj({"month": MONTH_PROP}),
                AGGREGATES,
                MonthArgs,
                self.budget_status,
            ),
            tool(
                "finance_category_trend",
                "Montant d'une catégorie mois par mois, jusqu'au mois en cours.",
                _obj(
                    {
                        "category": category,
                        "months": {"type": "integer", "minimum": 1, "maximum": 36},
                    },
                    ["category"],
                ),
                AGGREGATES,
                TrendArgs,
                self.category_trend,
            ),
            tool(
                "finance_recurring",
                "Abonnements et paiements réguliers : montant, cadence, prochaine échéance.",
                NONE,
                READ,
                NoArgs,
                self.recurring_list,
            ),
            tool(
                "finance_to_review",
                "Écritures sans catégorie, groupées par commerçant ; known_merchant dit si ce "
                "commerçant a déjà été catégorisé.",
                _obj(
                    {
                        "limit": {"type": "integer", "minimum": 1, "maximum": REVIEW_GROUPS},
                        "offset": {"type": "integer", "minimum": 0, "maximum": REVIEW_OFFSET_MAX},
                    }
                ),
                READ,
                ReviewArgs,
                self.to_review,
            ),
            tool(
                "finance_propose_category",
                "Propose une catégorie pour une écriture. Crée une carte à valider dans l'app ; "
                "rien n'est appliqué.",
                _obj(
                    {"entry_id": ENTRY_PROP, "category": category, "reason": REASON_PROP},
                    ["entry_id", "category"],
                ),
                PROPOSE,
                ProposeCategoryArgs,
                self.propose_category,
            ),
            tool(
                "finance_propose_categories",
                f"Propose une même catégorie pour plusieurs écritures (au plus {ENTRIES_MAX}), "
                "des achats uniques qu'aucune règle ne retrouvera. Une seule carte à valider ; "
                "rien n'est appliqué.",
                _obj(
                    {
                        "entry_ids": {
                            "type": "array",
                            "items": ENTRY_PROP,
                            "minItems": 1,
                            "maxItems": ENTRIES_MAX,
                        },
                        "category": category,
                        "reason": REASON_PROP,
                    },
                    ["entry_ids", "category"],
                ),
                PROPOSE,
                ProposeCategoriesArgs,
                self.propose_categories,
            ),
            tool(
                "finance_propose_rule",
                "Propose une règle : toute écriture qui contient le mot-clé prend la catégorie. "
                "La carte montre les écritures touchées ; rien n'est appliqué.",
                _obj(
                    {
                        "keyword": {"type": "string", "minLength": 3, "maxLength": 60},
                        "category": category,
                        "direction": {"type": "string", "enum": ["any", "debit", "credit"]},
                        "reason": REASON_PROP,
                    },
                    ["keyword", "category"],
                ),
                PROPOSE,
                ProposeRuleArgs,
                self.propose_rule,
            ),
            tool(
                "finance_propose_budget",
                "Propose une cible, dans la devise de base, pour une catégorie de dépense : "
                "mensuelle, ou annuelle (cadence year, suivie en cumul depuis janvier) pour les "
                "dépenses par à-coups ; rien n'est appliqué.",
                _obj(
                    {
                        "category": category,
                        "amount": {"type": "string", "pattern": r"^\d{1,7}(\.\d{1,2})?$"},
                        "cadence": {"type": "string", "enum": ["month", "year"]},
                        "reason": REASON_PROP,
                    },
                    ["category", "amount"],
                ),
                PROPOSE,
                ProposeBudgetArgs,
                self.propose_budget,
            ),
        ]
