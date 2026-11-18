"""Refonte du budget, lot C : « À venir » (charges fixes et abonnements du mois, payés ou
attendus), alerte d'une charge pas vue, nouvel abonnement repéré."""

from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient

from hub.core.context import HubContext
from hub.domains.finance.classement.app import insights, recurring, sentinels, upcoming
from hub.domains.finance.domain import FinanceDomain
from hub.platform.db import begin_immediate
from tests.finance.test_app_reads import (  # noqa: F401  (fixtures)
    client,
    ctx,
    fin,
    minor,
    year,
)
from tests.finance.test_double_sas import accept, create
from tests.finance.test_finance_api import token


def _refresh(fin: FinanceDomain, today: date) -> None:  # noqa: F811
    with begin_immediate(fin.engine()) as conn:
        recurring.refresh(conn, today)


def test_upcoming_lists_paid_charges_of_the_month(
    client: TestClient,  # noqa: F811
    ctx: HubContext,  # noqa: F811
    year: FinanceDomain,  # noqa: F811
) -> None:
    _refresh(year, date(2026, 10, 27))
    r = client.get(
        "/api/finance/budget/upcoming?month=2026-10", headers=token(ctx, "brain=finance")
    )
    assert r.status_code == 200
    u = r.json()
    rent = next(i for i in u["items"] if i["category"] == "logement")
    assert (rent["status"], rent["on"], minor(rent["amount"])) == ("paid", "2026-10-01", 150_000)
    assert u["late_count"] == 0
    # la portée aggregates n'a que les totaux
    agg = client.get("/api/finance/budget/upcoming?month=2026-10", headers=token(ctx, "aggregates"))
    assert agg.json()["items"] == []
    assert agg.json()["count"] == u["count"]


def test_a_charge_not_seen_three_days_after_its_day_is_late_and_alerts_once(
    year: FinanceDomain,  # noqa: F811
) -> None:
    today = date(2026, 11, 10)  # rien d'importé en novembre
    _refresh(year, today)
    with year.engine().connect() as conn:
        dues = upcoming.month_dues(conn, "2026-11", today)
        late = upcoming.late_fixed(conn, today)
        alerts = [a for a in sentinels.evaluate(conn, today) if a.kind == "fixed_missing"]
    rent = next(d for d in dues if d.category == "logement")
    assert (rent.on, rent.status) == ("2026-11-01", "late")
    assert rent in late
    assert any(a.key.startswith("fixed-missing:") for a in alerts)
    assert all("CHF" not in a.notice and "1500" not in a.title for a in alerts)
    # trois jours de grâce : le 3, rien n'est en retard
    with year.engine().connect() as conn:
        assert upcoming.late_fixed(conn, date(2026, 11, 3)) == []


def test_a_fixed_charge_tracked_by_year_is_not_expected_every_month(
    ctx: HubContext,  # noqa: F811
    year: FinanceDomain,  # noqa: F811
) -> None:
    params = {"category_id": "logement", "amount_minor": 1_800_000, "cadence": "year"}
    assert accept(ctx, create(ctx, "set_budget", params)).status == "applied"
    with year.engine().connect() as conn:
        assert "logement" in insights.yearly(conn)
        dues = upcoming.month_dues(conn, "2026-11", date(2026, 11, 10))
        late = upcoming.late_fixed(conn, date(2026, 11, 10))
    assert all(d.category != "logement" for d in dues)
    assert all(d.category != "logement" for d in late)


def test_a_fixed_category_without_target_gets_a_suggested_one(
    year: FinanceDomain,  # noqa: F811
) -> None:
    with year.engine().connect() as conn:
        assert upcoming._round_up(1_234_56) == 1_240_00
        dues = upcoming.month_dues(conn, "2026-10", date(2026, 10, 27))
    for d in dues:
        if d.kind == "fixed" and d.category == "logement":
            assert d.suggested_target is None  # elle a une cible


def test_a_new_subscription_is_announced_once_at_its_third_payment(
    year: FinanceDomain,  # noqa: F811
) -> None:
    _refresh(year, date(2026, 10, 27))
    with begin_immediate(year.engine()) as conn:
        conn.execute(
            upcoming.text("UPDATE recurring SET occurrences = 3 WHERE category_id = 'logement'")
        )
    with year.engine().connect() as conn:
        found = [k for k, *_ in upcoming.new_subscriptions(conn)]
        alerts = [
            a for a in sentinels.evaluate(conn, date(2026, 10, 27)) if a.kind == "recurring_new"
        ]
    assert found
    assert [a.key for a in alerts] == [f"recurring-new:{k}" for k in found]
