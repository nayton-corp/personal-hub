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
from hub.domains.finance.patrimoine.app.break_kinds import (
    DecideBreak,
    DecideBreakHandler,
    WithdrawBreakDecision,
    WithdrawBreakDecisionHandler,
    decide_break_inverse,
)
from hub.domains.finance.patrimoine.app.debt_kinds import (
    RecordDebtBalance,
    RecordDebtBalanceHandler,
    SaveDebt,
    SaveDebtHandler,
)
from hub.domains.finance.patrimoine.app.link_kinds import (
    LinkCryptoMoves,
    LinkCryptoMovesHandler,
    UnlinkCryptoMoves,
    UnlinkCryptoMovesHandler,
    link_inverse,
)
from hub.domains.finance.port import Finance
from hub.domains.finance.registre.app.correct_kinds import (
    CorrectEntry,
    CorrectEntryHandler,
    correct_inverse,
)
from hub.domains.finance.registre.app.entry_kinds import (
    AddNote,
    AddNoteHandler,
    CreateCategory,
    CreateCategoryHandler,
)
from hub.domains.finance.registre.app.period_kinds import (
    SetMonthStart,
    SetMonthStartHandler,
    month_start_inverse,
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
            RecategorizeHandler(domain),
            reversible=True,
            inverse=recategorize_inverse,
            ai_allowed=True,
        ),
        "create_rule": ProposalKind(CreateRule, CreateRuleHandler(domain), ai_allowed=True),
        "disable_rule": ProposalKind(DisableRule, DisableRuleHandler(), ai_allowed=True),
        "set_budget": ProposalKind(
            SetBudget,
            SetBudgetHandler(domain),
            reversible=True,
            inverse=budget_inverse,
            ai_allowed=True,
        ),
        "add_note": ProposalKind(AddNote, AddNoteHandler(), ai_allowed=True),
        "correct_entry": ProposalKind(
            CorrectEntry,
            CorrectEntryHandler(domain),
            reversible=True,
            inverse=correct_inverse,
            ai_allowed=True,
        ),
        "apply_import": ProposalKind(
            ApplyImport, ApplyImportHandler(domain), ttl=timedelta(days=7)
        ),
        "create_account": ProposalKind(
            CreateAccount, CreateAccountHandler(domain), ai_allowed=True
        ),
        "create_category": ProposalKind(CreateCategory, CreateCategoryHandler(), ai_allowed=True),
        "set_account_goal": ProposalKind(SetAccountGoal, SetAccountGoalHandler(), ai_allowed=True),
        "edit_account": ProposalKind(EditAccount, EditAccountHandler(), ai_allowed=True),
        "install_pack": ProposalKind(InstallPack, InstallPackHandler(), ai_allowed=True),
        "save_debt": ProposalKind(SaveDebt, SaveDebtHandler(domain), ai_allowed=True),
        "record_debt_balance": ProposalKind(
            RecordDebtBalance, RecordDebtBalanceHandler(domain), ai_allowed=True
        ),
        "decide_break": ProposalKind(
            DecideBreak,
            DecideBreakHandler(domain),
            reversible=True,
            inverse=decide_break_inverse,
            ai_allowed=True,
        ),
        "withdraw_break_decision": ProposalKind(
            WithdrawBreakDecision, WithdrawBreakDecisionHandler(domain), ai_allowed=True
        ),
        "set_month_start": ProposalKind(
            SetMonthStart,
            SetMonthStartHandler(domain),
            reversible=True,
            inverse=month_start_inverse,
            ai_allowed=True,
        ),
        "link_crypto_moves": ProposalKind(
            LinkCryptoMoves,
            LinkCryptoMovesHandler(domain),
            reversible=True,
            inverse=link_inverse,
            ai_allowed=True,
        ),
        "unlink_crypto_moves": ProposalKind(
            UnlinkCryptoMoves, UnlinkCryptoMovesHandler(domain), ai_allowed=True
        ),
        "categorize_rest": ProposalKind(
            CategorizeRest, CategorizeRestHandler(domain), ai_allowed=True
        ),
        "categorize_entries": ProposalKind(
            CategorizeEntries, CategorizeEntriesHandler(domain), ai_allowed=True
        ),
    }
