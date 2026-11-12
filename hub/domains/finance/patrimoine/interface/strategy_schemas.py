"""Formes de sortie de la route des stratégies ; règles : registre/interface/schemas.py."""

from __future__ import annotations

from hub.domains.finance.registre.interface.schemas import MoneyOut, Out


class StrategyRowOut(Out):
    key: str
    name: str
    value: MoneyOut
    cost: MoneyOut
    ratio_pct: str | None


class StrategyStepOut(Out):
    id: str
    key: str
    state: str
    opened_on: str
    planned: MoneyOut | None
    done: MoneyOut
    detail: dict[str, object]
    closed_on: str | None
    closed_by: str | None
    rows: list[StrategyRowOut] | None = None


class StrategyKeptOut(Out):
    done: int
    skipped: int


class StrategyOut(Out):
    id: str
    kind: str
    scope: str
    name: str
    phrase: str
    params: dict[str, object]
    note: str | None
    status: str
    state: str
    created_on: str
    level: dict[str, object]
    step: StrategyStepOut | None
    steps: list[StrategyStepOut]
    kept: StrategyKeptOut


class StrategyScopeOut(Out):
    key: str
    name: str
    kind: str
    value: MoneyOut


class StrategiesOut(Out):
    items: list[StrategyOut]
    scopes: list[StrategyScopeOut]
