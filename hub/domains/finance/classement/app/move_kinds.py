"""Déplacer du budget entre deux catégories pour un mois (refonte du budget, lot D) : « Reprendre
sur… » couvre un dépassement avec ce qui reste ailleurs. En ajout seul dans `budget_moves` ; la
somme des cibles du mois ne change pas et le mois suivant repart des cibles saisies
(insights.targets). Un mois clos ne se modifie pas."""

from __future__ import annotations

from datetime import date
from typing import Protocol

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import Connection, text

from hub.core.domain import Preview
from hub.domains.finance.classement.app.insights import (
    EXPENSE_GROUPS,
    category_modes,
    targets,
    yearly,
)
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
    def today(self) -> date: ...


class MoveBudget(Params):
    from_category: Slug
    to_category: Slug
    amount_minor: int = Field(gt=0, le=1_000_000_000)
    currency: str = Field(default_factory=base_currency)
    month: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}$")

    @field_validator("currency")
    @classmethod
    def _base(cls, value: str) -> str:
        if value != base_currency():
            raise ValueError("un déplacement est dans la devise de base de l'instance")
        return value


def _last(conn: Connection) -> int:
    return int(conn.execute(text("SELECT coalesce(max(seq), 0) FROM budget_moves")).scalar_one())


class MoveBudgetHandler:
    def __init__(self, domain: Host) -> None:
        self.domain = domain

    def _check(self, conn: Connection, params: MoveBudget) -> tuple[str, str, str, int]:
        """Le mois visé, les deux noms et la cible de départ ; une erreur dite en clair sinon."""
        current = period.month_of(self.domain.today())
        month = params.month or current
        if month < current:
            raise bad(f"le mois {month} est clos : un déplacement ne vaut que pour un mois ouvert")
        if params.from_category == params.to_category:
            raise bad("deux catégories différentes, s'il te plaît")
        src, src_grp = category_row(conn, params.from_category)
        dst, dst_grp = category_row(conn, params.to_category)
        modes, year = category_modes(conn), yearly(conn)
        for cat, grp in ((params.from_category, src_grp), (params.to_category, dst_grp)):
            if grp not in EXPENSE_GROUPS:
                raise bad(f"{cat} n'est pas une catégorie de dépense")
            if modes.get(cat, "target") != "target":
                raise bad(f"{cat} n'a pas de cible : passe-la en mode « avec cible »")
            if cat in year:
                raise bad(f"{cat} est suivie à l'année : un déplacement ne vaut que pour un mois")
        goal = targets(conn, month)
        have = goal[params.from_category].monthly if params.from_category in goal else 0
        if params.amount_minor > have:
            raise bad(f"{src} n'a que {shown_amount(have, params.currency)} de cible ce mois-ci")
        return month, src, dst, have

    def preview(self, conn: Connection, params: BaseModel) -> Preview:
        assert isinstance(params, MoveBudget)  # noqa: S101
        month, src, dst, have = self._check(conn, params)
        goal = targets(conn, month)
        other = goal[params.to_category].monthly if params.to_category in goal else 0
        amount, ccy = params.amount_minor, params.currency
        return Preview(
            summary=f"{shown_amount(amount, ccy)} de {src} vers {dst}, en {month} seulement",
            details={
                "month": month,
                "amount": Money(amount, ccy).to_api(),
                "from": {
                    "category": params.from_category,
                    "name": src,
                    "before": Money(have, ccy).to_api(),
                    "after": Money(have - amount, ccy).to_api(),
                },
                "to": {
                    "category": params.to_category,
                    "name": dst,
                    "before": Money(other, ccy).to_api(),
                    "after": Money(other + amount, ccy).to_api(),
                },
            },
            fingerprint=fp("move_budget", _last(conn), month, have, other),
        )

    def apply(self, conn: Connection, params: BaseModel, proposal_id: str) -> dict[str, object]:
        assert isinstance(params, MoveBudget)  # noqa: S101
        month, *_ = self._check(conn, params)
        conn.execute(
            text(
                "INSERT INTO budget_moves (month, from_category, to_category, amount_minor, "
                "currency, proposal_id, created_at) VALUES (:m, :f, :t, :a, :c, :p, :at)"
            ),
            {
                "m": month,
                "f": params.from_category,
                "t": params.to_category,
                "a": params.amount_minor,
                "c": params.currency,
                "p": proposal_id,
                "at": now_iso(),
            },
        )
        return {"month": month}


def move_inverse(
    params: dict[str, object], result: dict[str, object]
) -> tuple[str, dict[str, object]]:
    """Annuler : le même montant, en sens inverse, le même mois."""
    return "move_budget", {
        "from_category": params["to_category"],
        "to_category": params["from_category"],
        "amount_minor": params["amount_minor"],
        "currency": params.get("currency") or base_currency(),
        "month": result.get("month"),
    }
