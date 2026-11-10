"""Audit du 10/11, B1 et B3 : une charge fixe se juge à la tolérance près (« Payé », pas
« Dépassé de 0 »), et une cible à zéro retire la cible au lieu d'en faire une de zéro."""

from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient

from hub.core.context import HubContext
from hub.domains.finance.classement.app import sentinels
from hub.domains.finance.classement.app.budget_kinds import SetBudget, SetBudgetHandler
from hub.domains.finance.classement.model import pace
from hub.domains.finance.domain import FinanceDomain
from tests.finance.test_app_reads import (  # noqa: F401  (fixtures)
    client,
    ctx,
    fin,
    minor,
    set_budget,
    year,
)
from tests.finance.test_finance_api import token

NOW = pace.clock(date(2026, 10, 1), date(2026, 11, 1), date(2026, 10, 27))
FRANC = 100


def state(spent: int, group: str, target: int) -> str:
    return pace.line_state(spent, group, target, NOW, FRANC)


def test_a_fixed_charge_is_paid_within_one_unit_or_one_percent() -> None:
    assert state(133_605, "fixed", 133_600) == "paid"  # 1 336.05 pour 1 336 : pas « dépassé de 0 »
    assert state(133_600, "fixed", 133_600) == "paid"
    assert state(134_900, "fixed", 133_600) == "paid"  # +13 francs : sous 1 %
    assert state(135_000, "fixed", 133_600) == "over"  # +14 francs : au-delà
    assert state(132_300, "fixed", 133_600) == "paid"  # cible arrondie au-dessus du prélèvement
    assert state(130_000, "fixed", 133_600) == "ok"  # il en reste à payer
    # petite cible : 1 % ne dit rien, une unité de la devise fait la tolérance
    assert state(1_590, "fixed", 1_500) == "paid"
    assert state(1_601, "fixed", 1_500) == "over"
    assert pace.fixed_tolerance(1_500, FRANC) == FRANC
    assert pace.fixed_tolerance(133_600, FRANC) == 1_336


def test_a_variable_expense_is_still_judged_to_the_cent() -> None:
    assert state(40_001, "variable", 40_000) == "over"
    assert state(40_000, "variable", 40_000) in ("ok", "likely_over")


def test_budget_and_sentinels_agree_on_a_fixed_charge_over_by_cents(
    client: TestClient,  # noqa: F811
    ctx: HubContext,  # noqa: F811
    year: FinanceDomain,  # noqa: F811
) -> None:
    brain = token(ctx, "brain=finance")
    set_budget(year, "logement", 149_950)  # 1 500.00 payés pour une cible de 1 499.50
    b = client.get("/api/finance/budget?month=2026-10", headers=brain).json()
    line = {x["category"]: x for x in b["lines"]}["logement"]
    assert (line["state"], line["over"]) == ("paid", False)
    assert b["over_count"] == sum(1 for x in b["lines"] if x["state"] == "over")
    with year.engine().connect() as conn:
        seen = {
            p.category: p for p in sentinels.budget_projection(conn, "2026-10", date(2026, 10, 27))
        }
    assert seen["logement"].over is False  # pas d'alerte « budget dépassé » pour 50 centimes


def test_a_zero_target_removes_the_target(
    client: TestClient,  # noqa: F811
    ctx: HubContext,  # noqa: F811
    year: FinanceDomain,  # noqa: F811
) -> None:
    brain = token(ctx, "brain=finance")
    before = client.get("/api/finance/budget?month=2026-10", headers=brain).json()
    set_budget(year, "logement", 0)
    b = client.get("/api/finance/budget?month=2026-10", headers=brain).json()
    line = {x["category"]: x for x in b["lines"]}["logement"]
    assert (line["state"], line["target"], line["over"]) == ("untracked", None, False)
    assert minor(b["budget"]) == minor(before["budget"]) - 150_000
    with year.engine().connect() as conn:
        handler = SetBudgetHandler(year)
        gone = handler.preview(conn, SetBudget(category_id="alimentation", amount_minor=0))
        assert "cible retirée (avant" in gone.summary
        # une cible retirée n'est pas « avant 0.00 » quand on en remet une
        back = handler.preview(conn, SetBudget(category_id="logement", amount_minor=150_000))
        assert "avant" not in back.summary
        assert back.details["previous"] is None
