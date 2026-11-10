"""Proposition de budget (ticket L3-02) : la cible d'une catégorie, mensuelle ou annuelle, à
partir d'un mois ; le montant est gardé tel que saisi, avec sa cadence (audit M4)."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import Connection, text

from hub.core.domain import Preview
from hub.domains.finance.classement.app.insights import Target, target_of
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
    amount_minor: int = Field(ge=0, le=1_000_000_000)  # tel que saisi, dans sa cadence
    currency: str = Field(default_factory=base_currency)
    valid_from: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-01$")
    # suivi au mois ou à l'année (le montant est alors la cible annuelle) ; absent : inchangé
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
            "SELECT seq, monthly_minor, amount_minor, cadence FROM budgets WHERE category_id = :c "
            "ORDER BY seq DESC LIMIT 1"
        ),
        {"c": category_id},
    ).first()


def _current(conn: Connection, category_id: str) -> tuple[int, Target | None]:
    """(seq de la dernière ligne, sa cible) ; la cible est None sans budget, ou retirée (une
    dernière ligne à zéro)."""
    row = _budget_row(conn, category_id)
    if row is None:
        return 0, None
    target = target_of(
        row.monthly_minor, row.amount_minor, row.cadence, _cadence(conn, category_id)
    )
    return int(row.seq), target if target.amount > 0 else None


def _said(t: Target, currency: str) -> str:
    unit = "par an" if t.cadence == "year" else "par mois"
    return f"{shown_amount(t.amount, currency)} {unit}"


class SetBudgetHandler:
    def __init__(self, domain: Host) -> None:
        self.domain = domain

    def _from(self, params: SetBudget) -> str:
        return params.valid_from or f"{period.month_of(self.domain.today())}-01"

    def _target(self, conn: Connection, params: SetBudget) -> Target:
        return Target(params.amount_minor, params.cadence or _cadence(conn, params.category_id))

    def preview(self, conn: Connection, params: BaseModel) -> Preview:
        assert isinstance(params, SetBudget)  # noqa: S101
        name, grp = category_row(conn, params.category_id)
        if grp not in ("fixed", "variable"):
            raise bad("un budget porte sur une catégorie de dépenses")
        seq, before = _current(conn, params.category_id)
        target = self._target(conn, params)
        then = f" (avant {_said(before, params.currency)})" if before is not None else ""
        # zéro retire la cible : la catégorie redevient « hors budget » (audit du 10/11, B3)
        said = _said(target, params.currency) if target.amount > 0 else "cible retirée"
        return Preview(
            summary=f"Budget {name} : {said}{then}, dès {self._from(params)[:7]}",
            details={
                "category_id": params.category_id,
                "amount": Money(target.amount, params.currency).to_api(),
                "monthly": Money(target.monthly, params.currency).to_api(),
                "previous": (
                    Money(before.amount, params.currency).to_api() if before is not None else None
                ),
                "previous_cadence": before.cadence if before is not None else None,
                "valid_from": self._from(params),
                "cadence": target.cadence,
            },
            fingerprint=fp("set_budget", params.category_id, seq),
        )

    def apply(self, conn: Connection, params: BaseModel, proposal_id: str) -> dict[str, Any]:
        assert isinstance(params, SetBudget)  # noqa: S101
        _seq, previous = _current(conn, params.category_id)
        target = self._target(conn, params)
        seq = ledger.append(
            conn,
            "budgets",
            {
                "category_id": params.category_id,
                "monthly_minor": target.monthly,
                "amount_minor": target.amount,
                "cadence": target.cadence,
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
            "previous_amount": previous.amount if previous is not None else None,
            "previous_cadence": previous.cadence if previous is not None else before,
            "valid_from": self._from(params),
        }


def budget_inverse(params: dict[str, Any], result: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    previous = result.get("previous_amount")
    return "set_budget", {
        "category_id": params["category_id"],
        "amount_minor": 0 if previous is None else previous,
        "currency": params.get("currency") or base_currency(),
        "valid_from": result.get("valid_from"),
        "cadence": result.get("previous_cadence") or "month",
    }


def _cadence(conn: Connection, category_id: str) -> str:
    row = conn.execute(
        text("SELECT cadence FROM budget_cadence WHERE category_id = :c"), {"c": category_id}
    ).first()
    return str(row[0]) if row else "month"
