"""Formes de sortie des biens hors comptes et des frais des fonds ; règles :
registre/interface/schemas.py."""

from __future__ import annotations

from hub.domains.finance.patrimoine.interface.schemas import BalanceRecordOut
from hub.domains.finance.registre.interface.schemas import MoneyOut, Out


class GoodOut(Out):
    id: str
    key: str
    name: str
    kind: str
    currency: str
    yearly_change_pct: str | None
    closed_on: str | None
    value: MoneyOut
    stated: MoneyOut | None
    stated_on: str | None
    values: list[BalanceRecordOut]


class GoodListOut(Out):
    items: list[GoodOut]


class FundFeeOut(Out):
    isin: str
    name: str
    value: MoneyOut
    ter_pct: str | None  # None : frais inconnus
    source: str | None  # 'user' (saisi) ou 'issuer' (relevé par le collecteur)
    origin: str | None = None  # site où le TER a été relevé
    since: str | None = None  # jour de la saisie ou du relevé
    yearly_cost: MoneyOut | None


class FeesOut(Out):
    on_date: str
    currency: str
    items: list[FundFeeOut]
    yearly_cost: MoneyOut
    covered_value: MoneyOut
    unknown_value: MoneyOut
    cost_over_years: MoneyOut
    years: int
    assumed_return_pct: str
