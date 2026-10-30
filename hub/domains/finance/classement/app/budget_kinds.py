"""Proposition de budget (ticket L3-02) : la cible d'une catégorie, mensuelle ou annuelle, à
partir d'un mois."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import Connection, text

from hub.core.domain import Preview
from hub.domains.finance.registre.app import ledger
from hub.domains.finance.registre.app.kinds import (
    Params,
    Slug,
    bad,
    category_row,
    fp,
    shown_amount,
)
from hub.domains.finance.registre.model import period
from hub.kernel.clock import now_iso
from hub.kernel.money import Money, base_currency


class Host(Protocol):
    """Ce que le handler attend du domaine (`FinanceDomain` le remplit)."""

    def today(self) -> date: ...


class SetBudget(Params):
    category_id: Slug
    monthly_minor: int = Field(ge=0, le=100_000_000)
    currency: str = Field(default_factory=base_currency)
    valid_from: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-01$")
    # suivi au mois ou à l'année (cible annuelle = 12 × monthly_minor) ; absent : inchangé
    cadence: Literal["month", "year"] | None = None

    @field_validator("currency")
    @classmethod
    def _base(cls, value: str) -> str:
        if value != base_currency():
            raise ValueError("un budget est dans la devise de base de l'instance")
        return value


def _budget_row(conn: Connection, category_id: str) -> Any:
    return conn.execute(
        text(
            "SELECT seq, monthly_minor FROM budgets WHERE category_id = :c "
            "ORDER BY seq DESC LIMIT 1"
        ),
        {"c": category_id},
    ).first()


class SetBudgetHandler:
    def __init__(self, domain: Host) -> None:
        self.domain = domain

    def _from(self, params: SetBudget) -> str:
        return params.valid_from or f"{period.month_of(self.domain.today())}-01"

    def preview(self, conn: Connection, params: BaseModel) -> Preview:
        assert isinstance(params, SetBudget)  # noqa: S101
        name, grp = category_row(conn, params.category_id)
        if grp not in ("fixed", "variable"):
            raise bad("un budget porte sur une catégorie de dépenses")
        current = _budget_row(conn, params.category_id)
        before = int(current.monthly_minor) if current else None
        cadence = params.cadence or _cadence(conn, params.category_id)
        if cadence == "year":
            then = (
                f" (avant {shown_amount(before * 12, params.currency)})"
                if before is not None
                else ""
            )
            amount = f"{shown_amount(params.monthly_minor * 12, params.currency)} par an"
        else:
            then = f" (avant {shown_amount(before, params.currency)})" if before is not None else ""
            amount = f"{shown_amount(params.monthly_minor, params.currency)} par mois"
        return Preview(
            summary=f"Budget {name} : {amount}{then}, dès {self._from(params)[:7]}",
            details={
                "category_id": params.category_id,
                "monthly": Money(params.monthly_minor, params.currency).to_api(),
                "previous": Money(before, params.currency).to_api() if before is not None else None,
                "valid_from": self._from(params),
                "cadence": cadence,
            },
            fingerprint=fp("set_budget", params.category_id, current.seq if current else 0),
        )

    def apply(self, conn: Connection, params: BaseModel, proposal_id: str) -> dict[str, Any]:
        assert isinstance(params, SetBudget)  # noqa: S101
        current = _budget_row(conn, params.category_id)
        seq = ledger.append(
            conn,
            "budgets",
            {
                "category_id": params.category_id,
                "monthly_minor": params.monthly_minor,
                "currency": params.currency,
                "valid_from": self._from(params),
                "proposal_id": proposal_id,
                "created_at": now_iso(),
            },
        )
        before = _cadence(conn, params.category_id)
        if params.cadence is not None and params.cadence != before:
            conn.execute(
                text(
                    "INSERT INTO budget_cadence (category_id, cadence, updated_at, actor) "
                    "VALUES (:c, :k, :at, :p) ON CONFLICT (category_id) DO UPDATE SET "
                    "cadence = excluded.cadence, updated_at = excluded.updated_at, "
                    "actor = excluded.actor"
                ),
                {"c": params.category_id, "k": params.cadence, "at": now_iso(), "p": proposal_id},
            )
        return {
            "budget_seq": seq,
            "previous_minor": int(current.monthly_minor) if current else None,
            "previous_cadence": before,
            "valid_from": self._from(params),
        }


def budget_inverse(params: dict[str, Any], result: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    previous = result.get("previous_minor")
    return "set_budget", {
        "category_id": params["category_id"],
        "monthly_minor": 0 if previous is None else previous,
        "currency": params.get("currency") or base_currency(),
        "valid_from": result.get("valid_from"),
        "cadence": result.get("previous_cadence") or "month",
    }


def _cadence(conn: Connection, category_id: str) -> str:
    row = conn.execute(
        text("SELECT cadence FROM budget_cadence WHERE category_id = :c"), {"c": category_id}
    ).first()
    return str(row[0]) if row else "month"
