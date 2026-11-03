"""Proposition `set_month_start` (audit M9) : le jour où commence le mois budgétaire, pour les
mois à partir d'un mois donné (le mois en cours par défaut). Les mois d'avant gardent leur
découpage ; l'inverse repose la règle d'avant sur le même mois."""

from __future__ import annotations

from datetime import date
from typing import Any, Protocol

from pydantic import BaseModel, Field
from sqlalchemy import Connection, text

from hub.core.domain import Preview
from hub.domains.finance.registre.app.kinds import Params, fp
from hub.domains.finance.registre.model import period
from hub.kernel.clock import now_iso
from hub.kernel.ids import new_id


class Host(Protocol):
    def today(self) -> date: ...


class SetMonthStart(Params):
    start_day: int = Field(ge=1, le=period.MAX_DAY)
    valid_from: str | None = Field(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$")


def rules_read(conn: Connection) -> list[tuple[str, int]]:
    rows = conn.execute(
        text("SELECT valid_from, start_day FROM budget_period_rules ORDER BY created_at, id")
    ).fetchall()
    return [(str(r[0]), int(r[1])) for r in rows]


def _day_for(found: list[tuple[str, int]], month: str) -> int:
    day = 1
    for valid_from, d in sorted({v: d for v, d in found}.items()):
        if valid_from <= month:
            day = d
    return day


def _said(day: int) -> str:
    return "le 1er" if day == 1 else f"le {day}"


class SetMonthStartHandler:
    def __init__(self, domain: Host) -> None:
        self.domain = domain

    def _from(self, params: SetMonthStart) -> str:
        return params.valid_from or period.month_of(self.domain.today())

    def preview(self, conn: Connection, params: BaseModel) -> Preview:
        assert isinstance(params, SetMonthStart)  # noqa: S101
        found = rules_read(conn)
        valid_from = self._from(params)
        before = _day_for(found, valid_from)
        then = f" (avant {_said(before)})" if before != params.start_day else " (inchangé)"
        return Preview(
            summary=f"Mois budgétaire dès {valid_from} : commence {_said(params.start_day)}{then}",
            details={"start_day": params.start_day, "valid_from": valid_from, "previous": before},
            fingerprint=fp("set_month_start", valid_from, len(found), before),
        )

    def apply(self, conn: Connection, params: BaseModel, proposal_id: str) -> dict[str, Any]:
        assert isinstance(params, SetMonthStart)  # noqa: S101
        valid_from = self._from(params)
        before = _day_for(rules_read(conn), valid_from)
        conn.execute(
            text(
                "INSERT INTO budget_period_rules (id, valid_from, start_day, created_at, actor, "
                "proposal_id) VALUES (:id, :m, :d, :at, 'proposal', :p)"
            ),
            {
                "id": new_id(),
                "m": valid_from,
                "d": params.start_day,
                "at": now_iso(),
                "p": proposal_id,
            },
        )
        period.set_rules(rules_read(conn))
        return {"valid_from": valid_from, "start_day": params.start_day, "previous": before}


def month_start_inverse(
    params: dict[str, Any], result: dict[str, Any]
) -> tuple[str, dict[str, Any]]:
    """Repose la règle d'avant sur le même mois (la dernière posée l'emporte)."""
    return "set_month_start", {
        "start_day": int(result["previous"]),
        "valid_from": str(result["valid_from"]),
    }
