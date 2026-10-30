"""Les seize outils Finance de l'assistant (lot 7, puis la catégorisation par lot) : ceux de
chaque sous-contexte, dans l'ordre du catalogue. Règles communes : registre/interface/tools.py.
"""

from __future__ import annotations

from hub.core.domain import McpTool
from hub.domains.finance.classement.interface.tools import ClassementTools
from hub.domains.finance.patrimoine.interface.tools import PatrimoineTools
from hub.domains.finance.port import Finance
from hub.domains.finance.registre.interface.tools import RegistreTools

ORDER = (
    "finance_list_accounts",
    "finance_data_freshness",
    "finance_list_categories",
    "finance_month_summary",
    "finance_budget_status",
    "finance_category_trend",
    "finance_networth",
    "finance_recurring",
    "finance_to_review",
    "finance_search",
    "finance_propose_category",
    "finance_propose_categories",
    "finance_propose_rule",
    "finance_propose_budget",
    "finance_propose_note",
    "finance_proposal_status",
)


class FinanceTools:
    def __init__(self, domain: Finance) -> None:
        self.parts = (RegistreTools(domain), ClassementTools(domain), PatrimoineTools(domain))

    def build(self) -> list[McpTool]:
        registre = self.parts[0]
        with registre.engine.connect() as conn:
            ids = [c["id"] for c in registre._categories(conn)]
        category = {
            "type": "string",
            "enum": ids,
            "description": "Identifiant de catégorie (voir finance_list_categories).",
        }
        found = {t.name: t for part in self.parts for t in part.tools(category)}
        return [found[name] for name in ORDER]
