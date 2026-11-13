"""Les outils Finance de l'assistant (lot 7, puis la parité avec les routes et les types de
proposition, audit M11) : ceux de chaque sous-contexte, dans l'ordre du catalogue, puis une
proposition engendrée par type du Double Sas que l'assistant peut créer et qu'aucun outil écrit
à la main ne couvre. `ROUTE_TOOLS` dit quel outil répond à chaque route de lecture (None : la
route est réservée à l'app) ; `tests/finance/test_tools.py` tient la parité.
Règles communes : registre/interface/tools.py.
"""

from __future__ import annotations

from hub.core.domain import McpTool
from hub.domains.finance.classement.interface.tools import ClassementTools
from hub.domains.finance.classement.interface.tools_reads import ClassementReads
from hub.domains.finance.patrimoine.interface.tools import PatrimoineTools
from hub.domains.finance.port import Finance
from hub.domains.finance.registre.interface.generated import kind_tool
from hub.domains.finance.registre.interface.tools import RegistreTools
from hub.domains.finance.sources.interface.tools import SourcesTools

ORDER = (
    "finance_list_accounts",
    "finance_data_freshness",
    "finance_list_categories",
    "finance_settings",
    "finance_month_summary",
    "finance_budget_status",
    "finance_budget_months",
    "finance_flows",
    "finance_category_trend",
    "finance_networth",
    "finance_networth_history",
    "finance_holdings",
    "finance_performance",
    "finance_lookthrough",
    "finance_prices",
    "finance_breaks",
    "finance_debts",
    "finance_strategies",
    "finance_transfers",
    "finance_recurring",
    "finance_to_review",
    "finance_search",
    "finance_entries",
    "finance_entry",
    "finance_trades",
    "finance_rule_packs",
    "finance_pending_accounts",
    "finance_propose_category",
    "finance_propose_categories",
    "finance_propose_rule",
    "finance_propose_budget",
    "finance_propose_note",
    "finance_proposal_status",
)

# type de proposition → l'outil écrit à la main qui le crée (arguments plus simples) ; les autres
# types ouverts à l'assistant reçoivent `finance_propose_<type>`, engendré de leur modèle
HANDWRITTEN = {
    "recategorize": "finance_propose_category",
    "categorize_entries": "finance_propose_categories",
    "create_rule": "finance_propose_rule",
    "set_budget": "finance_propose_budget",
    "add_note": "finance_propose_note",
}
DESCRIPTIONS = {
    "correct_entry": "Propose de corriger le montant, la date ou le compte d'une écriture (une "
    "annulation puis une remplaçante, l'original reste).",
    "decide_break": "Propose de régler une rupture du rapprochement (finance_breaks) : coût "
    "saisi (`cost`, avec cost_minor), garder tel quel (`accept`), parti hors de mes comptes "
    "(`gone`).",
    "withdraw_break_decision": "Propose de retirer une décision de rapprochement : la rupture "
    "se rouvre.",
    "link_crypto_moves": "Propose de relier deux mouvements crypto : virement entre mes "
    "comptes, ou mise et sortie de staking.",
    "unlink_crypto_moves": "Propose de défaire un lien entre deux mouvements crypto.",
    "disable_rule": "Propose de désactiver une règle de catégorisation.",
    "create_category": "Propose une nouvelle catégorie (identifiant, nom, groupe).",
    "create_account": "Propose d'ouvrir un compte (finance_pending_accounts en liste à ouvrir).",
    "set_account_goal": "Propose l'objectif d'un compte (current, safety, projects, long_term, "
    "retirement).",
    "edit_account": "Propose les réglages d'un compte : nom, objectif, disponibilité, "
    "catégorie, masqué.",
    "install_pack": "Propose d'installer un pack de règles (finance_rule_packs).",
    "save_debt": "Propose une dette ou sa mise à jour (nom, prêteur, départ, mensualité, taux).",
    "record_debt_balance": "Propose un solde constaté d'une dette à une date.",
    "save_good": "Propose un bien hors comptes (logement, véhicule, objet, prêt accordé), sa "
    "mise à jour ou une nouvelle valeur à une date.",
    "save_strategy": "Propose d'écrire ou de modifier une stratégie (finance_strategies) : vendre "
    "par paliers, achat régulier, acheter une grosse baisse. Jamais d'ordre : le hub prévient.",
    "answer_strategy_step": "Propose la réponse à une étape atteinte d'une stratégie : c'est "
    "fait, plus tard, je passe.",
    "set_month_start": "Propose le jour où commence le mois budgétaire, dès un mois donné.",
    "categorize_rest": "Propose la même catégorie pour tout ce qui reste à classer d'un "
    "commerçant.",
}
# lecture par route (chemin sous /api/finance) → outil ; None : réservé à l'app (session passkey)
ROUTE_TOOLS: dict[str, str | None] = {
    "/accounts": "finance_list_accounts",
    "/accounts/pending": "finance_pending_accounts",
    "/kpis": "finance_networth",
    "/holdings": "finance_holdings",
    "/debts": "finance_debts",
    "/goods": None,
    "/strategies": "finance_strategies",
    "/breaks": "finance_breaks",
    "/lookthrough": "finance_lookthrough",
    "/transfers": "finance_transfers",
    "/networth/history": "finance_networth_history",
    "/performance": "finance_performance",
    "/prices": "finance_prices",
    "/entries": "finance_entries",
    "/entries/{entry_id}": "finance_entry",
    "/trades": "finance_trades",
    "/search": "finance_search",
    "/categories": "finance_list_categories",
    "/freshness": "finance_data_freshness",
    "/settings": "finance_settings",
    "/export.csv": None,
    "/imports/{import_id}": None,
    "/summary": "finance_month_summary",
    "/budget": "finance_budget_status",
    "/budget/totals": "finance_budget_months",
    "/budget/months": "finance_budget_months",
    "/flows": "finance_flows",
    "/trend": "finance_category_trend",
    "/review": "finance_to_review",
    "/todo": "finance_to_review",  # le même nombre « à classer »
    "/rules/packs": "finance_rule_packs",
    "/recurring": "finance_recurring",
}


def propose_tool_name(kind: str) -> str:
    return HANDWRITTEN.get(kind, f"finance_propose_{kind}")


class FinanceTools:
    def __init__(self, domain: Finance) -> None:
        self.domain = domain
        self.parts = (
            RegistreTools(domain),
            ClassementTools(domain),
            ClassementReads(domain),
            PatrimoineTools(domain),
            SourcesTools(domain),
        )

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
        generated = [
            kind_tool(propose_tool_name(name), name, kind, DESCRIPTIONS[name])
            for name, kind in self.domain.proposal_kinds.items()
            if kind.ai_allowed and name not in HANDWRITTEN
        ]
        return [found[name] for name in ORDER] + sorted(generated, key=lambda t: t.name)
