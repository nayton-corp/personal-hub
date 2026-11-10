"""Audit du 10/11, lot D : une charge fixe dit quand elle a été payée et vers quand on l'attend
(B2), et la tendance compare chaque mois à son budget, dans le périmètre du reste à vivre (B6)."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import text

from hub.core.context import HubContext
from hub.domains.finance.classement.app import due
from hub.domains.finance.domain import FinanceDomain
from hub.domains.finance.registre.model import period
from hub.platform.db import begin_immediate
from tests.finance.test_app_reads import (  # noqa: F401  (fixtures)
    client,
    ctx,
    fin,
    minor,
    year,
)
from tests.finance.test_finance_api import token


def test_a_fixed_charge_says_when_it_was_paid_and_when_it_is_due(
    client: TestClient,  # noqa: F811
    ctx: HubContext,  # noqa: F811
    year: FinanceDomain,  # noqa: F811
) -> None:
    brain = token(ctx, "brain=finance")
    b = client.get("/api/finance/budget?month=2026-10", headers=brain).json()
    lines = {x["category"]: x for x in b["lines"]}
    # le loyer part le 1er de chaque mois : payé le 1er, et attendu ce jour-là d'après l'habitude
    assert lines["logement"]["paid_on"] == "2026-10-01"
    assert lines["logement"]["expected_on"] == "2026-10-01"
    # une dépense variable n'a ni échéance ni date de paiement
    assert lines["alimentation"]["paid_on"] is None
    assert lines["alimentation"]["expected_on"] is None
    # un mois clos garde la date du paiement, sans échéance à attendre
    past = client.get("/api/finance/budget?month=2026-08", headers=brain).json()
    old = {x["category"]: x for x in past["lines"]}["logement"]
    assert (old["paid_on"], old["expected_on"]) == ("2026-08-01", None)
    # trois mois : le dernier paiement de la période
    q = client.get("/api/finance/budget?month=2026-10&period=q", headers=brain).json()
    assert {x["category"]: x for x in q["lines"]}["logement"]["paid_on"] == "2026-09-01"


def test_the_expected_day_follows_the_budget_month(
    year: FinanceDomain,  # noqa: F811
) -> None:
    with year.engine().connect() as conn:
        assert due.expected(conn, "2026-11") == {"logement": "2026-11-01"}
        # mois budgétaire du 25 au 24 : le loyer du 1er tombe au 8e jour de la période
        period.set_start_day(25)
        try:
            assert due.expected(conn, "2026-11") == {"logement": "2026-11-01"}
            start, end = period.bounds("2026-11")
            assert due.last_paid(conn, start, end) == {}  # novembre n'est pas encore importé
        finally:
            period.set_start_day(1)


def test_the_trend_compares_each_month_to_its_budget(
    client: TestClient,  # noqa: F811
    ctx: HubContext,  # noqa: F811
    year: FinanceDomain,  # noqa: F811
) -> None:
    brain = token(ctx, "brain=finance")
    series = client.get("/api/finance/budget/months?month=2026-10&months=3", headers=brain).json()
    aug, _sep, octo = series["series"]
    # budget 1 750 (loyer 1 500, alimentation 250) ; août : 1 500 + 300 + 80 dépensés
    assert (minor(aug["budget"]), minor(aug["budgeted_expenses"]), minor(aug["over"])) == (
        175_000,
        188_000,
        13_000,
    )
    b = client.get("/api/finance/budget?month=2026-10", headers=brain).json()
    assert minor(octo["budgeted_expenses"]) == minor(b["budgeted_expenses"])
    assert minor(octo["over"]) == max(0, -minor(b["rest_to_live"]))
    # une catégorie suivie à l'année sort du budget du mois, donc du dépassement
    with begin_immediate(year.engine()) as conn:
        conn.execute(
            text(
                "INSERT INTO budget_cadence (category_id, cadence, updated_at, actor) "
                "VALUES ('restaurants', 'year', 'x', 'test')"
            )
        )
    again = client.get("/api/finance/budget/months?month=2026-10&months=3", headers=brain).json()
    assert minor(again["series"][0]["budgeted_expenses"]) == 180_000
    assert minor(again["series"][0]["over"]) == 5_000
