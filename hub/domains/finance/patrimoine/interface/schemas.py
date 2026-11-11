"""Formes de sortie des routes du patrimoine (audit M10) ; règles : registre/interface/schemas.py.
Les clés variables (compte, enveloppe, ligne de performance) sont des dictionnaires typés."""

from __future__ import annotations

from pydantic import ConfigDict, Field

from hub.domains.finance.registre.interface.schemas import ClbdOut, MoneyOut, Out


class SpendRuleOut(Out):
    rule_id: str
    category_id: str


class AccountOut(Out):
    id: str
    institution: str
    name: str
    kind: str
    iban: str | None
    external_ref: str | None
    liquid: bool
    budget_account: bool
    availability: str
    availability_set: bool
    availability_auto: str
    goal: str
    goal_set: bool
    category: str | None
    hidden: bool
    target: MoneyOut | None
    spend_rule: SpendRuleOut | None
    balance: MoneyOut
    value: MoneyOut
    missing_prices: list[str]
    last_booking: str | None
    last_clbd: ClbdOut | None


class AccountListOut(Out):
    items: list[AccountOut]


class ChangeOut(Out):
    since: str
    amount: MoneyOut
    ratio: str | None


class Pillar3aOut(Out):
    year: int
    cap: MoneyOut
    paid: MoneyOut
    margin: MoneyOut
    source: str


class KpisOut(Out):
    month: str
    as_of: str
    currency: str
    net_worth: MoneyOut
    envelopes: dict[str, MoneyOut]
    change_1m: ChangeOut
    change_ytd: ChangeOut
    deposits_ytd: MoneyOut
    market_ytd: MoneyOut
    income: MoneyOut
    expenses: MoneyOut
    savings: MoneyOut
    savings_rate: str | None
    budget: MoneyOut | None
    budget_used: str | None
    rest_to_live: MoneyOut | None
    days_left: int
    liquid: MoneyOut
    months_covered: str | None
    savings_rate_3m: str | None
    stale_accounts: int
    to_categorize: int
    unmatched_transfers: int
    pillar3a: Pillar3aOut | None
    last_statement: str | None
    missing_fx: list[str]
    missing_prices: list[str]


class CryptoAssetOut(Out):
    quantity: str
    value: MoneyOut
    cost: MoneyOut
    unrealized: MoneyOut
    realized: MoneyOut
    income: MoneyOut
    result: MoneyOut
    unknown_cost_value: MoneyOut


class CryptoResultOut(Out):
    on_date: str
    currency: str
    value: MoneyOut
    cost: MoneyOut
    unrealized: MoneyOut
    realized: MoneyOut
    result: MoneyOut
    income: MoneyOut
    result_usd: MoneyOut | None
    crypto_effect: MoneyOut | None
    fx_effect: MoneyOut | None
    unknown_cost_value: MoneyOut
    arrived_from_outside: MoneyOut
    sent_outside_cost: MoneyOut
    unexplained_out_cost: MoneyOut
    sold_without_history: MoneyOut
    missing_prices: bool
    by_asset: dict[str, CryptoAssetOut]


class CryptoOut(Out):
    invested: MoneyOut
    value: MoneyOut
    result: MoneyOut
    missing_prices: bool
    since_purchase: CryptoResultOut | None


class HoldingOut(Out):
    account_id: str
    account: str | None
    isin: str
    name: str
    asset_class: str | None
    sub_class: str | None
    quantity: str
    price: str | None
    price_currency: str | None
    kind: str
    price_date: str | None
    value: MoneyOut
    cost: MoneyOut | None
    gain: MoneyOut | None
    weight: str | None


class HoldingsOut(Out):
    on_date: str
    currency: str
    items: list[HoldingOut]
    value: MoneyOut
    cost: MoneyOut | None
    missing_prices: list[str]
    crypto: CryptoOut | None


class BalanceRecordOut(Out):
    on_date: str
    amount: MoneyOut


class DebtOut(Out):
    id: str
    key: str
    name: str
    lender: str
    kind: str
    currency: str
    original: MoneyOut
    rate_pct: str | None
    day_count: str
    payment: MoneyOut | None
    ends_on: str | None
    category_id: str | None
    category_name: str | None
    account_id: str | None
    account_name: str | None
    closed_on: str | None
    balance: MoneyOut
    stated: MoneyOut | None
    stated_on: str | None
    paid_since: MoneyOut | None
    interest_since: MoneyOut | None
    payments_since: int
    last_payment: str | None
    usual_payment: MoneyOut | None
    projected_end: str | None
    balances: list[BalanceRecordOut]


class DebtListOut(Out):
    items: list[DebtOut]


class BreakOut(Out):
    id: str
    kind: str
    account_id: str
    account: str
    asset: str
    symbol: str
    quantity: str | None
    value: MoneyOut | None
    since: str
    until: str | None
    cause: str
    actions: list[str]


class BreaksOut(Out):
    on_date: str
    currency: str
    items: list[BreakOut]
    count: int
    open_value: MoneyOut
    invested: MoneyOut
    explained: MoneyOut
    completeness: str | None
    tolerance: MoneyOut


class BucketAssetOut(Out):
    isin: str | None  # l'instrument, ou None pour les liquidités d'un compte
    account_id: str | None = None
    name: str
    value: MoneyOut


class BucketOut(Out):
    bucket: str
    code: str | None  # home, europe, north_america, japan, pacific, emerging, crypto, unknown…
    kind: str  # named | cash | undetailed (part qu'un fonds ne détaille pas) | unknown
    estimated: bool  # tirée de la classe ou de la devise de cotation, pas d'une composition
    value: MoneyOut
    weight: str
    count: int  # actifs qui remplissent la case (`assets` n'en nomme que les premiers)
    assets: list[BucketAssetOut]


class UnpricedOut(Out):
    isin: str
    account_id: str
    name: str


class LookthroughOut(Out):
    dimension: str
    on_date: str
    currency: str
    total: MoneyOut  # ce qui est réparti : la somme des cases
    owed: MoneyOut  # dettes et soldes négatifs, à part ; total + owed = la valeur affichée
    covered: str | None  # part sûre : ni estimée, ni non répartie, ni inconnue
    compositions_since: str | None
    items: list[BucketOut]
    unpriced: list[UnpricedOut]  # positions sans cours, hors de la répartition


class UnmatchedOut(Out):
    id: str
    account_id: str
    account: str
    date: str
    amount: MoneyOut


class TransfersOut(Out):
    pairs: int
    by_method: dict[str, int]
    unmatched: int
    unmatched_items: list[UnmatchedOut] | None = None


class NetworthPointOut(Out):
    on_date: str
    net_worth: MoneyOut
    deposits_cum: MoneyOut
    by_envelope: dict[str, MoneyOut]
    by_account: dict[str, MoneyOut]


class NetworthHistoryOut(Out):
    as_of: str | None
    currency: str
    items: list[NetworthPointOut]


class LineSummaryOut(Out):
    start: MoneyOut
    end: MoneyOut
    net_flows: MoneyOut
    gain: MoneyOut
    price_effect: MoneyOut
    income: MoneyOut
    fees: MoneyOut
    twr: str | None
    twr_yearly: str | None
    mwr: str | None
    personal: str | None = None
    complete: bool


class PerformancePointOut(Out):
    on_date: str
    value: MoneyOut
    net_flows: MoneyOut
    gain: MoneyOut
    twr: str | None
    personal: str | None = None
    drawdown: str | None
    complete: bool


class PeriodRowOut(Out):
    period: str
    gain: MoneyOut
    net_flows: MoneyOut
    twr: str | None


class PerformanceEventOut(Out):
    on_date: str
    kind: str
    amount: MoneyOut


class RiskOut(Out):
    volatility: str | None
    max_drawdown: str | None
    peak_on: str | None
    trough_on: str | None
    recovered_on: str | None


class ExtremeOut(Out):
    on_date: str
    value: MoneyOut


class ExtremesOut(Out):
    high: ExtremeOut
    low: ExtremeOut


class PerformanceOut(Out):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    currency: str
    from_: str | None = Field(default=None, alias="from")
    to: str | None = None
    first_day: str | None = None
    lines: int
    items: list[PerformancePointOut]
    extremes: ExtremesOut | None = None
    summary: LineSummaryOut | None
    owned: LineSummaryOut | None = None
    by_account: dict[str, LineSummaryOut]
    by_asset: dict[str, LineSummaryOut]
    by_line: dict[str, LineSummaryOut]
    by_month: list[PeriodRowOut]
    by_year: list[PeriodRowOut]
    events: list[PerformanceEventOut]
    missing: list[str]
    risk: RiskOut | None


class PricePointOut(Out):
    on_date: str
    price: str


class PricesOut(Out):
    isin: str
    name: str | None
    currency: str | None
    mixed_currencies: bool
    items: list[PricePointOut]
