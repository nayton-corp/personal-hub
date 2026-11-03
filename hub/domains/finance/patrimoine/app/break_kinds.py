"""Propositions sur les ruptures du rapprochement (audit C5) : `decide_break` règle une rupture
ouverte aujourd'hui (coût saisi, garder tel quel, parti), comme `POST /breaks/decide` le faisait
sans Double Sas ; son inverse `withdraw_break_decision` retire la décision par une ligne de
retrait, et la rupture se rouvre à la lecture suivante. L'assistant peut proposer la décision ;
toi seul la valides."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import Connection

from hub.core.domain import Preview
from hub.domains.finance.patrimoine.app import decisions, reconcile
from hub.domains.finance.registre.app.kinds import Params, bad, fp, shown_amount
from hub.kernel.money import base_currency


class Host(Protocol):
    def today(self) -> date: ...

    def refresh_snapshots(self) -> object: ...


NAMES = {
    "unexplained": "parts sans historique",
    "sent_outside": "envoi hors de mes comptes",
    "arrived_outside": "arrivée hors de mes comptes",
    "no_price": "sans cours",
    "stale_price": "cours ancien",
}
SAID = {"cost": "au prix d'achat saisi", "accept": "gardée telle quelle", "gone": "partie"}


class DecideBreak(Params):
    break_id: str = Field(min_length=3, max_length=200)  # `<rupture>|<compte>|<actif>`
    decision: Literal["cost", "accept", "gone"]
    cost_minor: int | None = Field(default=None, ge=0, le=10**13)
    note: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def _cost_needs_amount(self) -> DecideBreak:
        if self.decision == "cost" and self.cost_minor is None:
            raise ValueError("un prix d'achat saisi demande son montant")
        return self


class DecideBreakHandler:
    def __init__(self, domain: Host) -> None:
        self.domain = domain

    def _break(self, conn: Connection, break_id: str) -> reconcile.Break:
        on = self.domain.today().isoformat()
        found = {b.id: b for b in reconcile.report(conn, on).breaks}
        b = found.get(break_id)
        if b is None:
            raise bad("rupture inconnue ou déjà réglée")
        if b.kind not in decisions.KINDS:
            raise bad("rupture inconnue")
        return b

    def preview(self, conn: Connection, params: BaseModel) -> Preview:
        assert isinstance(params, DecideBreak)  # noqa: S101
        b = self._break(conn, params.break_id)
        if params.decision not in decisions.DECISIONS.get(b.kind, ()):
            raise bad(f"{params.decision} ne règle pas une rupture {b.kind}")
        public = b.public(reconcile.names(conn))
        cost = (
            f" : {shown_amount(params.cost_minor, base_currency())}"
            if params.decision == "cost" and params.cost_minor is not None
            else ""
        )
        return Preview(
            summary=(
                f"Rupture « {NAMES[b.kind]} » sur {public['account']} ({public['symbol']}) "
                f"{SAID[params.decision]}{cost}"
            ),
            details={"break": public, "decision": params.decision, "cost_minor": params.cost_minor},
            fingerprint=fp(
                "decide_break", b.id, b.since, None if b.quantity is None else str(b.quantity)
            ),
        )

    def apply(self, conn: Connection, params: BaseModel, proposal_id: str) -> dict[str, Any]:
        assert isinstance(params, DecideBreak)  # noqa: S101
        d = reconcile.decide(
            conn,
            self.domain.today().isoformat(),
            params.break_id,
            params.decision,
            cost_minor=params.cost_minor,
            note=params.note,
            actor="proposal",
            proposal_id=proposal_id,
        )
        return {"decision": d.public()}

    def after_commit(self, params: BaseModel, result: dict[str, Any]) -> None:
        self.domain.refresh_snapshots()


def decide_break_inverse(
    params: dict[str, Any], result: dict[str, Any]
) -> tuple[str, dict[str, Any]]:
    return "withdraw_break_decision", {"decision_id": str(result["decision"]["id"])}


class WithdrawBreakDecision(Params):
    decision_id: str = Field(min_length=1, max_length=40)


class WithdrawBreakDecisionHandler:
    def __init__(self, domain: Host) -> None:
        self.domain = domain

    def _decision(self, conn: Connection, decision_id: str) -> decisions.Decision:
        d = decisions.get(conn, decision_id)
        if d is None:
            raise bad("décision inconnue ou déjà retirée")
        return d

    def preview(self, conn: Connection, params: BaseModel) -> Preview:
        assert isinstance(params, WithdrawBreakDecision)  # noqa: S101
        d = self._decision(conn, params.decision_id)
        names = reconcile.names(conn)
        return Preview(
            summary=(
                f"Retire la décision « {SAID[d.decision]} » sur {names.get(d.account_id, '?')} "
                f"({d.asset}) : la rupture se rouvre"
            ),
            details={"decision": d.public()},
            fingerprint=fp("withdraw_break_decision", d.id),
        )

    def apply(self, conn: Connection, params: BaseModel, proposal_id: str) -> dict[str, Any]:
        assert isinstance(params, WithdrawBreakDecision)  # noqa: S101
        d = self._decision(conn, params.decision_id)
        decisions.withdraw(conn, d.id, proposal_id=proposal_id, actor="proposal")
        return {"decision_id": d.id}

    def after_commit(self, params: BaseModel, result: dict[str, Any]) -> None:
        self.domain.refresh_snapshots()
