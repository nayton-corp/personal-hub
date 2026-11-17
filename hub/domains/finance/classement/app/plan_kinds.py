"""Proposition des revenus attendus (refonte du budget, lot A) : le montant du plan du mois, à
partir d'un mois, en ajout seul dans `plan_income`. Sans montant, le plan revient à la moyenne
des revenus des trois derniers mois (plan.py)."""

from __future__ import annotations

from datetime import date
from typing import Protocol

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import Connection, text

from hub.core.domain import Preview
from hub.domains.finance.classement.app.plan import entered_income
from hub.domains.finance.registre.app.kinds import Params, fp, shown_amount
from hub.domains.finance.registre.model import period
from hub.kernel.clock import now_iso
from hub.kernel.money import Money, base_currency


class Host(Protocol):
    def today(self) -> date: ...


class SetPlanIncome(Params):
    # revenus attendus par mois ; None : la moyenne des trois derniers mois
    amount_minor: int | None = Field(default=None, ge=0, le=1_000_000_000)
    currency: str = Field(default_factory=base_currency)
    valid_from: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-01$")

    @field_validator("currency")
    @classmethod
    def _base(cls, value: str) -> str:
        if value != base_currency():
            raise ValueError("les revenus attendus sont dans la devise de base de l'instance")
        return value


def _said(amount: int | None, currency: str) -> str:
    if amount is None:
        return "la moyenne des trois derniers mois"
    return f"{shown_amount(amount, currency)} par mois"


def _last(conn: Connection) -> tuple[int, int | None] | None:
    row = conn.execute(
        text("SELECT seq, amount_minor FROM plan_income ORDER BY seq DESC LIMIT 1")
    ).first()
    return None if row is None else (int(row[0]), None if row[1] is None else int(row[1]))


class SetPlanIncomeHandler:
    def __init__(self, domain: Host) -> None:
        self.domain = domain

    def _from(self, params: SetPlanIncome) -> str:
        return params.valid_from or f"{period.month_of(self.domain.today())}-01"

    def preview(self, conn: Connection, params: BaseModel) -> Preview:
        assert isinstance(params, SetPlanIncome)  # noqa: S101
        start = self._from(params)
        before = entered_income(conn, start[:7])
        last = _last(conn)
        then = f" (avant {_said(before[1], params.currency)})" if before is not None else ""
        amount = params.amount_minor
        return Preview(
            summary=f"Revenus attendus : {_said(amount, params.currency)}{then}, dès {start[:7]}",
            details={
                "amount": (Money(amount, params.currency).to_api() if amount is not None else None),
                "previous": (
                    Money(before[1], params.currency).to_api()
                    if before is not None and before[1] is not None
                    else None
                ),
                "valid_from": start,
            },
            fingerprint=fp("set_plan_income", last[0] if last else 0),
        )

    def apply(self, conn: Connection, params: BaseModel, proposal_id: str) -> dict[str, object]:
        assert isinstance(params, SetPlanIncome)  # noqa: S101
        start = self._from(params)
        before = entered_income(conn, start[:7])
        conn.execute(
            text(
                "INSERT INTO plan_income (amount_minor, currency, valid_from, proposal_id, "
                "created_at) VALUES (:a, :c, :f, :p, :at)"
            ),
            {
                "a": params.amount_minor,
                "c": params.currency,
                "f": start,
                "p": proposal_id,
                "at": now_iso(),
            },
        )
        return {"previous_amount": before[1] if before is not None else None, "valid_from": start}


def plan_income_inverse(
    params: dict[str, object], result: dict[str, object]
) -> tuple[str, dict[str, object]]:
    return "set_plan_income", {
        "amount_minor": result.get("previous_amount"),
        "currency": params.get("currency") or base_currency(),
        "valid_from": result.get("valid_from"),
    }
