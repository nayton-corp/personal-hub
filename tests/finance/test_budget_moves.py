"""Refonte du budget, lot D : déplacer du budget d'une catégorie à une autre pour un mois
(« Reprendre sur… »), annulable, sans toucher au mois suivant ni à un mois clos."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from hub.core import proposals
from hub.core.context import HubContext
from hub.core.errors import Problem
from hub.domains.finance.classement.app import insights
from hub.domains.finance.domain import FinanceDomain
from hub.platform.db import begin_immediate
from tests.finance.test_app_reads import (  # noqa: F401  (fixtures)
    client,
    ctx,
    fin,
    year,
)
from tests.finance.test_double_sas import APP, accept, create


def _targets(fin: FinanceDomain, month: str) -> dict[str, int]:  # noqa: F811
    with fin.engine().connect() as conn:
        return {c: t.monthly for c, t in insights.targets(conn, month).items()}


def _move(amount: int) -> dict[str, object]:
    return {"from_category": "logement", "to_category": "alimentation", "amount_minor": amount}


def test_a_move_shifts_targets_for_the_month_only_and_reverts(
    ctx: HubContext,  # noqa: F811
    year: FinanceDomain,  # noqa: F811
) -> None:
    before = _targets(year, "2026-10")
    p = create(ctx, "move_budget", _move(5_000))
    assert "en 2026-10 seulement" in p.preview["summary"]
    assert accept(ctx, p).status == "applied"
    after = _targets(year, "2026-10")
    assert (after["logement"], after["alimentation"]) == (145_000, 30_000)
    assert sum(after.values()) == sum(before.values())
    assert _targets(year, "2026-11") == before  # le mois suivant repart des cibles saisies
    with ctx.core.engine.connect() as conn:
        fresh = proposals.get(conn, p.id)
    assert proposals.revert(ctx, APP, fresh, None).status == "applied"
    assert _targets(year, "2026-10") == before


def test_a_move_is_refused_beyond_the_target_for_a_closed_month_or_off_target(
    ctx: HubContext,  # noqa: F811
    year: FinanceDomain,  # noqa: F811
) -> None:
    for params, said in (
        (_move(150_001), "n'a que"),
        ({**_move(1_000), "month": "2026-09"}, "clos"),
        ({**_move(1_000), "to_category": "salaire"}, "pas une catégorie de dépense"),
        ({**_move(1_000), "to_category": "logement"}, "différentes"),
    ):
        with pytest.raises(Problem, match=said):
            create(ctx, "move_budget", params)


def test_budget_moves_are_append_only(year: FinanceDomain) -> None:  # noqa: F811
    with begin_immediate(year.engine()) as conn:
        conn.execute(
            text(
                "INSERT INTO budget_moves (month, from_category, to_category, amount_minor, "
                "currency, created_at) VALUES ('2026-10', 'logement', 'alimentation', 1, 'CHF', "
                "'x')"
            )
        )
    for statement in ("UPDATE budget_moves SET amount_minor = 2", "DELETE FROM budget_moves"):
        with (
            pytest.raises(IntegrityError, match="append_only"),
            begin_immediate(year.engine()) as conn,
        ):
            conn.execute(text(statement))
