"""Propositions de catégorie (ticket L3-02) : reclasser une écriture (ou la répartir entre
plusieurs catégories), classer tout le reste d'une période, classer un lot d'écritures."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import Connection, text

from hub.core.domain import Preview
from hub.domains.finance.registre.app import ledger
from hub.domains.finance.registre.app.kinds import (
    SAMPLE,
    EntryId,
    Params,
    Slug,
    bad,
    category_row,
    entry_brief,
    entry_row,
    fp,
    shown_amount,
    totals_by_currency,
)
from hub.domains.finance.registre.model import merchant
from hub.kernel.clock import now_iso

if TYPE_CHECKING:
    pass


class Line(Params):
    category_id: Slug
    amount_minor: int


class Recategorize(Params):
    entry_id: EntryId
    category_id: Slug
    lines: list[Line] | None = Field(default=None, min_length=2, max_length=20)
    suggested: bool = False  # proposée par un modèle et acceptée telle quelle


class RecategorizeHandler:
    def preview(self, conn: Connection, params: BaseModel) -> Preview:
        assert isinstance(params, Recategorize)  # noqa: S101
        e = entry_row(conn, params.entry_id)
        if e.kind != "movement":
            raise bad("seules les écritures de mouvement se catégorisent")
        name, _grp = category_row(conn, params.category_id)
        if params.lines is not None:
            for line in params.lines:
                category_row(conn, line.category_id)
                if line.amount_minor == 0 or (line.amount_minor < 0) != (e.amount_minor < 0):
                    raise bad("chaque ligne a le signe de l'écriture et n'est pas nulle")
            if sum(x.amount_minor for x in params.lines) != e.amount_minor:
                raise bad("la ventilation doit sommer au montant de l'écriture")
        before = e.category_id
        split = f", ventilée en {len(params.lines)}" if params.lines else ""
        return Preview(
            summary=f"1 écriture → {name}{split} ({shown_amount(e.amount_minor, e.currency)})",
            details={
                "entries": [entry_brief(e)],
                "count": 1,
                "from_category": before,
                "to_category": params.category_id,
                "lines": [x.model_dump() for x in params.lines] if params.lines else None,
            },
            fingerprint=fp("recategorize", e.id, e.categorization_seq or 0),
        )

    def apply(self, conn: Connection, params: BaseModel, proposal_id: str) -> dict[str, Any]:
        assert isinstance(params, Recategorize)  # noqa: S101
        e = entry_row(conn, params.entry_id)
        seq = ledger.append(
            conn,
            "categorizations",
            {
                "entry_seq": e.seq,
                "category_id": params.category_id,
                "source": "suggestion_accepted" if params.suggested else "user",
                "rule_id": None,
                "proposal_id": proposal_id,
                "created_at": now_iso(),
            },
        )
        for i, line in enumerate(params.lines or []):
            ledger.append(
                conn,
                "categorization_lines",
                {
                    "categorization_seq": seq,
                    "line": i,
                    "category_id": line.category_id,
                    "amount_minor": line.amount_minor,
                },
            )
        return {
            "entry_id": e.id,
            "categorization_seq": seq,
            "previous_category": e.category_id,
        }


def recategorize_inverse(
    params: dict[str, Any], result: dict[str, Any]
) -> tuple[str, dict[str, Any]]:
    previous = result.get("previous_category")
    if previous is None:
        raise ValueError("l'écriture n'avait pas de catégorie")
    return "recategorize", {"entry_id": params["entry_id"], "category_id": previous}


REST_MAX = 5000


class CategorizeRest(Params):
    """Classe d'un coup les écritures encore sans catégorie d'avant une date (le vieil
    historique, souvent des achats uniques qu'on ne classera jamais un par un)."""

    before: date
    direction: Literal["debit", "credit"] = "debit"
    category_id: Slug


def _rest(conn: Connection, params: CategorizeRest) -> list[Any]:
    sign = "<" if params.direction == "debit" else ">"
    return list(
        conn.execute(
            text(
                "SELECT e.seq, e.id, e.booking_date, e.amount_minor, e.currency, e.counterparty, "
                "e.label FROM entries e LEFT JOIN v_entry_shown vc ON vc.entry_seq = e.seq "
                "WHERE vc.category_id IS NULL AND e.kind = 'movement' AND e.booking_date < :d "
                f"AND e.amount_minor {sign} 0 ORDER BY e.booking_date DESC, e.seq DESC LIMIT :n"
            ),
            {"d": params.before.isoformat(), "n": REST_MAX + 1},
        ).fetchall()
    )


class CategorizeRestHandler:
    def preview(self, conn: Connection, params: BaseModel) -> Preview:
        assert isinstance(params, CategorizeRest)  # noqa: S101
        name, _grp = category_row(conn, params.category_id)
        rows = _rest(conn, params)
        if len(rows) > REST_MAX:
            raise bad(f"plus de {REST_MAX} écritures : choisis une date plus ancienne")
        if not rows:
            raise bad("aucune écriture sans catégorie avant cette date")
        sens = "dépense" if params.direction == "debit" else "entrée"
        n = len(rows)
        return Preview(
            summary=(
                f"{n} {sens}{'s' if n > 1 else ''} sans catégorie d'avant le "
                f"{params.before.strftime('%d.%m.%Y')} → {name}"
            ),
            details={
                "count": n,
                "totals": totals_by_currency([(int(r.amount_minor), r.currency) for r in rows]),
                "entries": [entry_brief(r) for r in rows[:SAMPLE]],
                "to_category": params.category_id,
            },
            fingerprint=fp("categorize_rest", sorted(r.id for r in rows)),
        )

    def apply(self, conn: Connection, params: BaseModel, proposal_id: str) -> dict[str, Any]:
        assert isinstance(params, CategorizeRest)  # noqa: S101
        rows = _rest(conn, params)
        at = now_iso()
        for r in rows:
            ledger.append(
                conn,
                "categorizations",
                {
                    "entry_seq": r.seq,
                    "category_id": params.category_id,
                    "source": "user",
                    "rule_id": None,
                    "proposal_id": proposal_id,
                    "created_at": at,
                },
            )
        return {"changed": len(rows)}


ENTRIES_MAX = 30  # une carte reste lisible : on la relit avant le Face ID


class CategorizeEntries(Params):
    """Une catégorie pour quelques écritures choisies : les achats uniques, qu'aucune règle ne
    retrouvera, proposés par lot plutôt qu'une carte par écriture."""

    entry_ids: list[EntryId] = Field(min_length=1, max_length=ENTRIES_MAX)
    category_id: Slug
    suggested: bool = False  # proposée par un modèle et acceptée telle quelle

    @field_validator("entry_ids")
    @classmethod
    def _distinct(cls, v: list[str]) -> list[str]:
        if len(set(v)) != len(v):
            raise ValueError("écriture en double")
        return v


def _entries(conn: Connection, ids: list[str]) -> list[Any]:
    marks = ", ".join(f":i{n}" for n in range(len(ids)))
    rows = conn.execute(
        text(
            "SELECT e.seq, e.id, e.kind, e.booking_date, e.amount_minor, e.currency, "
            "e.counterparty, e.label, vc.category_id, vc.categorization_seq "
            "FROM entries e LEFT JOIN v_entry_category vc ON vc.entry_seq = e.seq "
            f"WHERE e.id IN ({marks}) ORDER BY e.booking_date DESC, e.seq DESC"
        ),
        {f"i{n}": i for n, i in enumerate(ids)},
    ).fetchall()
    if len(rows) != len(ids):
        raise bad("écriture inconnue")
    if any(r.kind != "movement" for r in rows):
        raise bad("seules les écritures de mouvement se catégorisent")
    return list(rows)


class CategorizeEntriesHandler:
    def preview(self, conn: Connection, params: BaseModel) -> Preview:
        assert isinstance(params, CategorizeEntries)  # noqa: S101
        name, _grp = category_row(conn, params.category_id)
        rows = _entries(conn, params.entry_ids)
        n = len(rows)
        totals = totals_by_currency([(int(r.amount_minor), r.currency) for r in rows])
        shown = " + ".join(f"{t['display']} {t['currency']}" for t in totals)
        return Preview(
            summary=f"{n} écriture{'s' if n > 1 else ''} → {name} ({shown})",
            details={
                "count": n,
                "totals": totals,
                "entries": [{**entry_brief(r), "merchant": merchant.key(r.label)} for r in rows],
                "to_category": params.category_id,
            },
            fingerprint=fp(
                "categorize_entries", sorted((r.id, r.categorization_seq or 0) for r in rows)
            ),
        )

    def apply(self, conn: Connection, params: BaseModel, proposal_id: str) -> dict[str, Any]:
        assert isinstance(params, CategorizeEntries)  # noqa: S101
        at = now_iso()
        for r in _entries(conn, params.entry_ids):
            ledger.append(
                conn,
                "categorizations",
                {
                    "entry_seq": r.seq,
                    "category_id": params.category_id,
                    "source": "suggestion_accepted" if params.suggested else "user",
                    "rule_id": None,
                    "proposal_id": proposal_id,
                    "created_at": at,
                },
            )
        return {"changed": len(params.entry_ids)}
