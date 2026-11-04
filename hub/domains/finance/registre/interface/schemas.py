"""Formes de sortie des routes du registre (audit M10) : ce que l'app, l'assistant et l'OpenAPI
peuvent tenir pour acquis.

Chaque champ connu est typé ; un champ que le code ajoute sans le déclarer passe
(`extra="allow"`) plutôt que de casser une route en service, et le test de contrat
(`tests/finance/test_api_contracts.py`) le signale pour qu'il soit déclaré. Les montants sont
des `MoneyOut` (centimes, devise, texte), les parts et les taux du texte décimal.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class Out(BaseModel):
    model_config = ConfigDict(extra="allow")


class MoneyOut(Out):
    minor: int
    currency: str
    display: str


class CategoryRefOut(Out):
    id: str
    source: str


class EntryOut(Out):
    id: str
    account_id: str
    kind: str
    booking_date: str
    value_date: str | None
    amount: MoneyOut
    counterparty: str | None
    merchant: str | None
    counterparty_iban: str | None
    label: str | None
    remittance: str | None
    bank_tx_code: str | None
    category: CategoryRefOut | None


class EntryListOut(Out):
    items: list[EntryOut]
    next_cursor: str | None


class CategorizationOut(Out):
    category_id: str
    source: str
    rule_id: str | None
    at: str


class NoteOut(Out):
    text: str
    at: str


class CorrectionOut(Out):
    id: str
    amount: MoneyOut
    booking_date: str


class EntryDetailOut(EntryOut):
    categorizations: list[CategorizationOut]
    notes: list[NoteOut]
    corrections: list[CorrectionOut]


class TradeOut(Out):
    id: str
    account_id: str
    trade_date: str
    isin: str
    name: str
    quantity: str
    amount: MoneyOut


class TradeListOut(Out):
    items: list[TradeOut]


class EntrySearchOut(Out):
    items: list[EntryOut]


class CategoryOut(Out):
    id: str
    name: str
    group: str
    active: bool


class CategoryListOut(Out):
    items: list[CategoryOut]


class ClbdOut(Out):
    on_date: str
    amount: MoneyOut
    gap: MoneyOut


class FreshnessOut(Out):
    account_id: str
    name: str
    institution: str
    hidden: bool
    last_import: str | None
    last_data: str | None
    last_clbd: ClbdOut | None
    collector: str | None


class FreshnessListOut(Out):
    items: list[FreshnessOut]


class PeriodOut(Out):
    start: str
    end: str


class MonthRuleOut(Out):
    valid_from: str
    start_day: int


class SettingsOut(Out):
    month_start_day: int
    current_month: str
    current_period: PeriodOut
    rules: list[MonthRuleOut]
