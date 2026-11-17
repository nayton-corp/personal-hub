"""Refonte du budget, lot A : plan du mois (revenus attendus, épargne visée, non attribué, reste
et par jour), remboursements nettés, provisions annuelles au rythme, courbe jour par jour."""

from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient

from hub.core.context import HubContext
from hub.domains.finance.classement.app import plan
from hub.domains.finance.classement.app.totals import Line, Totals, netted
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
from tests.finance.test_double_sas import accept, create
from tests.finance.test_finance_api import token

SALARY = 500_000
SPENT_OCT = 150_000 + 30_000 + 8_000 + 5_000  # loyer, épicerie, bistrot, kiosque (au 27)


def budget(c: TestClient, hub: HubContext, month: str = "2026-10") -> dict[str, object]:
    r = c.get(f"/api/finance/budget?month={month}", headers=token(hub, "brain=finance"))
    assert r.status_code == 200
    return r.json()


def test_plan_numbers_follow_h1_and_fall_back_to_targets() -> None:
    # revenus 5 000, épargne 600, cibles 1 750, dépensé 1 930
    assert plan.plan_numbers(500_000, 60_000, 175_000, 193_000, None) == (265_000, 247_000)
    # sans revenus attendus : le reste d'avant (cibles − dépensé), pas de non attribué
    assert plan.plan_numbers(None, 60_000, 175_000, 193_000, -18_000) == (None, -18_000)
    # ce qui est déjà promis (charges attendues, provisions) sort aussi du reste
    assert plan.plan_numbers(500_000, 60_000, 175_000, 0, None, reserved=150_000)[1] == 290_000
    assert plan.per_day(247_000, 4, True) == 49_400  # 5 jours, aujourd'hui compris
    assert plan.per_day(-1, 4, True) is None
    assert plan.per_day(247_000, 4, False) is None


def test_a_refund_lowers_its_category_but_never_below_zero() -> None:
    lines = [
        Line("alimentation", "variable", -30_000, 3),
        Line("sante", "variable", 12_000, 1),  # remboursé au-delà de son coût sur la période
        Line("salaire", "income", 500_000, 1),
    ]
    t = Totals.of(lines)
    assert (t.variable, t.income) == (30_000, 512_000)
    assert t.savings == 500_000 - 30_000 + 12_000  # revenus − dépenses ne change pas
    assert [x.group for x in netted(lines)] == ["variable", "income", "income"]


def test_yearly_provision_pace_set_aside_and_likely_over() -> None:
    now = pace.clock(date(2026, 10, 1), date(2026, 11, 1), date(2026, 10, 16))
    elapsed = pace.year_elapsed(10, now)
    assert elapsed == (9 * 31 + 16, 12 * 31)
    assert pace.set_aside(150_000, 300_000, 10) == 50_000  # 1 500 sur octobre, nov., déc.
    assert pace.set_aside(350_000, 300_000, 10) == 0
    assert pace.yearly_state(310_000, 300_000, elapsed, 10) == "over"
    assert pace.yearly_state(290_000, 300_000, elapsed, 10) == "likely_over"
    assert pace.yearly_state(200_000, 300_000, elapsed, 10) == "ok"
    # en février, trop tôt pour projeter
    feb = pace.year_elapsed(2, pace.clock(date(2026, 2, 1), date(2026, 3, 1), date(2026, 2, 27)))
    assert pace.yearly_state(100_000, 300_000, feb, 2) == "ok"
    assert pace.yearly_state(1, None, feb, 2) == "untracked"


def test_the_plan_of_the_month_from_the_average_income(
    client: TestClient,  # noqa: F811
    ctx: HubContext,  # noqa: F811
    year: FinanceDomain,  # noqa: F811
) -> None:
    b = budget(client, ctx)
    p = b["plan"]
    assert (minor(p["income"]), p["income_source"]) == (SALARY, "average")
    assert minor(p["savings"]) == 0
    assert minor(p["targets"]) == 175_000
    assert minor(p["unassigned"]) == SALARY - 175_000
    assert minor(b["budgeted_expenses"]) == SPENT_OCT
    assert minor(p["rest"]) == SALARY - SPENT_OCT
    assert minor(p["per_day"]) == (SALARY - SPENT_OCT) // (b["days_left"] + 1)
    # la courbe : un point par jour jusqu'à aujourd'hui, le dernier vaut le dépensé
    assert len(b["daily"]) == 27
    assert b["daily"][-1] == SPENT_OCT
    assert b["daily"][0] == 150_000  # le loyer du 1er
    assert len(b["prev_daily"]) == 30
    assert b["prev_daily"][-1] == 188_000


def test_expected_income_and_savings_target_set_by_proposals(
    client: TestClient,  # noqa: F811
    ctx: HubContext,  # noqa: F811
    year: FinanceDomain,  # noqa: F811
) -> None:
    accept(ctx, create(ctx, "set_plan_income", {"amount_minor": 480_000}))
    accept(ctx, create(ctx, "set_budget", {"category_id": "epargne-3a", "amount_minor": 60_000}))
    p = budget(client, ctx)["plan"]
    assert (minor(p["income"]), p["income_source"]) == (480_000, "set")
    assert minor(p["savings"]) == 60_000
    assert minor(p["unassigned"]) == 480_000 - 60_000 - 175_000
    assert minor(p["rest"]) == 480_000 - 60_000 - SPENT_OCT
    line = p["savings_lines"][0]
    assert (line["category"], minor(line["target"]), minor(line["done"])) == (
        "epargne-3a",
        60_000,
        60_000,
    )
    # sans montant : retour à la moyenne ; l'épargne ne compte pas dans le budget des dépenses
    accept(ctx, create(ctx, "set_plan_income", {"amount_minor": None}))
    b = budget(client, ctx)
    assert b["plan"]["income_source"] == "average"
    assert minor(b["budget"]) == 175_000


def test_aggregates_scope_has_no_curve_nor_savings_detail(
    client: TestClient,  # noqa: F811
    ctx: HubContext,  # noqa: F811
    year: FinanceDomain,  # noqa: F811
) -> None:
    r = client.get("/api/finance/budget?month=2026-10", headers=token(ctx, "aggregates"))
    b = r.json()
    assert (b["daily"], b["prev_daily"], b["plan"]["savings_lines"]) == ([], [], [])
    assert b["plan"]["rest"] is not None


def test_charges_still_expected_are_taken_out_of_the_rest(
    year: FinanceDomain,  # noqa: F811
) -> None:
    from hub.domains.finance.classement.app import budget as budget_app
    from hub.domains.finance.classement.app import recurring
    from hub.platform.db import begin_immediate

    today = date(2026, 11, 3)  # rien d'importé en novembre : le loyer du 1er est attendu
    with begin_immediate(year.engine()) as conn:
        recurring.refresh(conn, today)
    with year.engine().connect() as conn:
        b = budget_app.budget(conn, "2026-11", "m", today, aggregates_only=False)
    p = b["plan"]
    pending = minor(p["pending"])
    assert pending >= 150_000  # le loyer au moins
    assert minor(p["rest"]) == minor(p["income"]) - minor(b["budgeted_expenses"]) - pending
    # un mois clos n'attend plus rien
    with year.engine().connect() as conn:
        oct_ = budget_app.budget(conn, "2026-09", "m", date(2026, 10, 27), aggregates_only=False)
    assert minor(oct_["plan"]["pending"]) == 0
