"""Formes de sortie des routes du classement et du budget (audit M10) ; règles :
registre/interface/schemas.py. Les états d'une ligne ou d'une période sont des mots du serveur
(`classement/model/pace.py`), jamais recalculés par l'app."""

from __future__ import annotations

from pydantic import ConfigDict, Field

from hub.domains.finance.registre.interface.schemas import MoneyOut, Out


class MissingFxOut(Out):
    currency: str
    on_date: str
    count: int


class CategoryTotalOut(Out):
    category: str
    group: str
    count: int
    total: MoneyOut


class SummaryOut(Out):
    month: str
    currency: str
    income: MoneyOut
    expenses: MoneyOut
    savings: MoneyOut
    transfers: MoneyOut
    uncategorized: MoneyOut
    by_group: dict[str, MoneyOut]
    by_category: list[CategoryTotalOut]
    missing_fx: list[MissingFxOut]


class YearlyOut(Out):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    from_: str | None = Field(default=None, alias="from")
    target: MoneyOut
    spent: MoneyOut
    ratio: str | None


class BudgetLineOut(Out):
    category: str
    name: str
    group: str
    count: int
    spent: MoneyOut
    target: MoneyOut | None
    ratio: str | None
    over: bool
    rest: MoneyOut | None = None
    projected: MoneyOut | None = None
    state: str | None = None
    yearly: YearlyOut | None = None
    paid_on: str | None = None  # charge fixe : son dernier paiement de la période
    expected_on: str | None = None  # charge fixe du mois en cours : le jour habituel


class BudgetStateOut(Out):
    kind: str
    over_by: MoneyOut | None


class BudgetOut(Out):
    month: str
    period: str
    months: list[str]
    start: str
    end: str
    current: bool
    days_left: int
    currency: str
    income: MoneyOut
    expenses: MoneyOut
    budgeted_expenses: MoneyOut
    budget: MoneyOut | None
    rest_to_live: MoneyOut | None
    projection: MoneyOut | None
    expected: str | None
    pace: str | None
    over_count: int
    state: BudgetStateOut
    lines: list[BudgetLineOut]
    missing_fx: list[MissingFxOut]


class BudgetTotalsOut(Out):
    month: str
    period: str
    months: list[str]
    start: str
    end: str
    currency: str
    income: MoneyOut
    expenses: MoneyOut
    fixed: MoneyOut
    variable: MoneyOut
    savings: MoneyOut
    invested: MoneyOut
    budget: MoneyOut | None
    budget_used: str | None
    rate: str | None


class MonthTotalsOut(Out):
    month: str
    income: MoneyOut
    expenses: MoneyOut
    fixed: MoneyOut
    variable: MoneyOut
    savings: MoneyOut
    invested: MoneyOut
    rate: str | None
    budget: MoneyOut | None = None  # le budget du mois (hors catégories suivies à l'année)
    budgeted_expenses: MoneyOut | None = None  # ce qui en a été dépensé
    over: MoneyOut | None = None  # le dépassement, 0 sinon


class BudgetMonthsOut(Out):
    currency: str
    series: list[MonthTotalsOut]


class FlowItemOut(Out):
    category: str
    name: str
    count: int
    total: MoneyOut


class FlowGroupOut(Out):
    group: str
    total: MoneyOut
    items: list[FlowItemOut]


class FlowsOut(Out):
    month: str
    period: str
    months: list[str]
    currency: str
    income: MoneyOut
    sources: list[FlowItemOut]
    groups: list[FlowGroupOut]
    remainder: MoneyOut


class TrendPointOut(Out):
    month: str
    count: int
    total: MoneyOut


class TrendOut(Out):
    category: str | None
    series: list[TrendPointOut]


class ReviewSampleOut(Out):
    id: str
    account_id: str
    booking_date: str
    amount: MoneyOut
    label: str | None
    remittance: str | None


class ReviewGroupOut(Out):
    key: str
    counterparty: str
    direction: str
    count: int
    total: MoneyOut
    min: MoneyOut
    max: MoneyOut
    first_date: str
    last_date: str
    accounts: list[str]
    bank_tx_codes: list[str]
    labels: list[str]
    remittances: list[str]
    history: list[str]
    guess: str | None
    entry_ids: list[str]
    samples: list[ReviewSampleOut]


class ReviewOut(Out):
    groups: list[ReviewGroupOut]


class PackOut(Out):
    name: str
    label: str
    description: str
    country: str | None
    version: int
    installed: int | None
    rules: int


class RulePacksOut(Out):
    items: list[PackOut]
    suggested: list[str]
    active_rules: int


class RecurringByCategoryOut(Out):
    category: str
    monthly: MoneyOut


class RecurringItemOut(Out):
    label: str
    category: str | None
    category_name: str | None
    cadence: str
    amount: MoneyOut
    last_amount: MoneyOut
    monthly: MoneyOut
    occurrences: int
    last_date: str
    next_date: str
    active: bool
    account: str | None
    last_entry_id: str | None


class RecurringOut(Out):
    as_of: str
    count: int
    due_30d: int
    monthly_total: list[MoneyOut]
    by_category: list[RecurringByCategoryOut]
    items: list[RecurringItemOut] | None = None
