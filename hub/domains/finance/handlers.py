"""Types de proposition du domaine Finance (ticket L3-02, section 5 de la spécification).

Chaque handler a un aperçu en lecture seule, dont l'empreinte couvre exactement ce que l'effet
va toucher, et un `apply()` appelé dans la transaction `BEGIN IMMEDIATE` ouverte par le cœur.
Le cœur compare l'empreinte relue sous verrou à celle de la carte validée : si elle a changé,
la carte passe à la révision suivante au lieu de s'appliquer.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta

from hub.core.domain import ProposalKind
from hub.domains.finance.classement.app.budget_kinds import (
    SetBudget,
    SetBudgetHandler,
    budget_inverse,
)
from hub.domains.finance.classement.app.categorize_kinds import (
    CategorizeEntries,
    CategorizeEntriesHandler,
    CategorizeRest,
    CategorizeRestHandler,
    Recategorize,
    RecategorizeHandler,
    recategorize_inverse,
)
from hub.domains.finance.classement.app.rule_kinds import (
    CreateRule,
    CreateRuleHandler,
    DisableRule,
    DisableRuleHandler,
    InstallPack,
    InstallPackHandler,
)
from hub.domains.finance.patrimoine.app.account_kinds import (
    EditAccount,
    EditAccountHandler,
    SetAccountGoal,
    SetAccountGoalHandler,
)
from hub.domains.finance.patrimoine.app.debt_kinds import (
    RecordDebtBalance,
    RecordDebtBalanceHandler,
    SaveDebt,
    SaveDebtHandler,
)
from hub.domains.finance.port import Finance
from hub.domains.finance.registre.app.entry_kinds import (
    AddNote,
    AddNoteHandler,
    CreateCategory,
    CreateCategoryHandler,
)
from hub.domains.finance.sources.app.import_kinds import (
    ApplyImport,
    ApplyImportHandler,
    CreateAccount,
    CreateAccountHandler,
)


def build_kinds(domain: Finance) -> Mapping[str, ProposalKind]:
    return {
        "recategorize": ProposalKind(
            Recategorize,
            RecategorizeHandler(),
            reversible=True,
            inverse=recategorize_inverse,
            ai_allowed=True,
        ),
        "create_rule": ProposalKind(CreateRule, CreateRuleHandler(), ai_allowed=True),
        "disable_rule": ProposalKind(DisableRule, DisableRuleHandler()),
        "set_budget": ProposalKind(
            SetBudget,
            SetBudgetHandler(domain),
            reversible=True,
            inverse=budget_inverse,
            ai_allowed=True,
        ),
        "add_note": ProposalKind(AddNote, AddNoteHandler(), ai_allowed=True),
        "apply_import": ProposalKind(
            ApplyImport, ApplyImportHandler(domain), ttl=timedelta(days=7)
        ),
        "create_account": ProposalKind(CreateAccount, CreateAccountHandler(domain)),
        "create_category": ProposalKind(CreateCategory, CreateCategoryHandler()),
        "set_account_goal": ProposalKind(SetAccountGoal, SetAccountGoalHandler()),
        "edit_account": ProposalKind(EditAccount, EditAccountHandler()),
        "install_pack": ProposalKind(InstallPack, InstallPackHandler()),
        "save_debt": ProposalKind(SaveDebt, SaveDebtHandler(domain)),
        "record_debt_balance": ProposalKind(RecordDebtBalance, RecordDebtBalanceHandler(domain)),
        "categorize_rest": ProposalKind(CategorizeRest, CategorizeRestHandler()),
        "categorize_entries": ProposalKind(
            CategorizeEntries, CategorizeEntriesHandler(), ai_allowed=True
        ),
    }
