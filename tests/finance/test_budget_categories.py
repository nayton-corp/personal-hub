"""Refonte du budget, lot Q : modes de catégorie (avec cible, suivie sans cible, hors budget) et
gestion des catégories (créer, modifier, fusionner, archiver)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from hub.core.context import HubContext
from hub.core.errors import Problem
from hub.domains.finance.classement.app import totals
from hub.domains.finance.domain import FinanceDomain
from hub.domains.finance.packs import pack
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

SPENT_OCT = 150_000 + 30_000 + 8_000 + 5_000


def get(c: TestClient, hub: HubContext, path: str) -> dict[str, object]:
    r = c.get(f"/api/finance/{path}", headers=token(hub, "brain=finance"))
    assert r.status_code == 200, r.text
    return r.json()


def cats(c: TestClient, hub: HubContext) -> dict[str, dict[str, object]]:
    return {x["id"]: x for x in get(c, hub, "categories")["items"]}


def do(hub: HubContext, kind: str, params: dict[str, object]) -> None:
    accept(hub, create(hub, kind, params))


def test_default_modes_come_from_the_country_pack() -> None:
    ch = pack("CH")
    assert ch.mode_of("twint-particuliers") == "off_budget"
    assert ch.mode_of("retraits") == "tracked"
    assert ch.mode_of("divers") == "tracked"  # générique, quel que soit le pays
    assert ch.mode_of("alimentation") == "target"
    assert pack("ZZ").mode_of("twint-particuliers") == "target"


def test_off_budget_leaves_spent_rest_and_curve_and_shows_a_net(
    client: TestClient,  # noqa: F811
    ctx: HubContext,  # noqa: F811
    year: FinanceDomain,  # noqa: F811
) -> None:
    do(ctx, "edit_category", {"category_id": "restaurants", "mode": "off_budget"})
    c = cats(client, ctx)["restaurants"]
    assert (c["mode"], c["mode_set"]) == ("off_budget", True)
    b = get(client, ctx, "budget?month=2026-10")
    assert "restaurants" not in {x["category"] for x in b["lines"]}
    assert minor(b["budgeted_expenses"]) == SPENT_OCT - 8_000
    assert b["daily"][-1] == SPENT_OCT - 8_000
    off = {x["category"]: x for x in b["off_budget"]}
    assert minor(off["restaurants"]["net"]) == 8_000


def test_tracked_has_no_target_and_counts_in_spent(
    client: TestClient,  # noqa: F811
    ctx: HubContext,  # noqa: F811
    year: FinanceDomain,  # noqa: F811
) -> None:
    do(ctx, "edit_category", {"category_id": "alimentation", "mode": "tracked"})
    b = get(client, ctx, "budget?month=2026-10")
    line = {x["category"]: x for x in b["lines"]}["alimentation"]
    assert (line["state"], line["target"]) == ("untracked", None)
    assert minor(b["budget"]) == 150_000
    assert minor(b["budgeted_expenses"]) == SPENT_OCT


def test_merge_moves_entries_rules_and_target_and_keeps_closed_months(
    client: TestClient,  # noqa: F811
    ctx: HubContext,  # noqa: F811
    year: FinanceDomain,  # noqa: F811
) -> None:
    with year.engine().connect() as conn:
        before = totals.summary(conn, "2026-09", aggregates_only=False)
    set_budget(year, "restaurants", 10_000)
    do(ctx, "merge_categories", {"from_id": "restaurants", "into_id": "alimentation"})
    with year.engine().connect() as conn:
        after = totals.summary(conn, "2026-09", aggregates_only=False)
    assert (after["income"], after["expenses"]) == (before["income"], before["expenses"])
    b = get(client, ctx, "budget?month=2026-10")
    lines = {x["category"]: x for x in b["lines"]}
    assert "restaurants" not in lines
    assert minor(lines["alimentation"]["spent"]) == 38_000
    assert minor(lines["alimentation"]["target"]) == 35_000  # 250 + 100 par mois
    c = cats(client, ctx)
    assert c["restaurants"]["active"] is False
    do(ctx, "archive_category", {"category_id": "restaurants", "archived": False})
    assert cats(client, ctx)["restaurants"]["active"] is True


def test_group_change_is_refused_when_closed_months_would_move(
    client: TestClient,  # noqa: F811
    ctx: HubContext,  # noqa: F811
    year: FinanceDomain,  # noqa: F811
) -> None:
    with pytest.raises(Problem, match="mois clos"):
        create(ctx, "edit_category", {"category_id": "restaurants", "grp": "fixed"})
    do(ctx, "create_category", {"name": "Cours de piano", "grp": "variable", "icon": "music:4"})
    c = cats(client, ctx)["cours-de-piano"]
    assert (c["name"], c["group"], c["icon"], c["mode"]) == (
        "Cours de piano",
        "variable",
        "music:4",
        "target",
    )
    do(ctx, "edit_category", {"category_id": "cours-de-piano", "grp": "fixed", "name": "Piano"})
    c = cats(client, ctx)["cours-de-piano"]
    assert (c["name"], c["group"]) == ("Piano", "fixed")
    with pytest.raises(Problem, match="déjà"):
        create(ctx, "create_category", {"name": "piano", "grp": "variable"})


def test_an_archived_category_no_longer_classifies(
    client: TestClient,  # noqa: F811
    ctx: HubContext,  # noqa: F811
    year: FinanceDomain,  # noqa: F811
) -> None:
    do(ctx, "archive_category", {"category_id": "restaurants"})
    with pytest.raises(Problem, match="inactive"):
        create(
            ctx,
            "set_budget",
            {"category_id": "restaurants", "amount_minor": 10_000},
        )
    # l'historique reste juste : le mois clos garde ses restaurants
    b = get(client, ctx, "budget?month=2026-09")
    assert minor({x["category"]: x for x in b["lines"]}["restaurants"]["spent"]) == 8_000


def test_an_off_budget_net_growing_three_months_raises_one_alert(
    year: FinanceDomain,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import date

    from hub.domains.finance.classement.app import insights, sentinels
    from hub.domains.finance.classement.app.totals import Line

    nets = {"2026-07": -2_000, "2026-08": -5_000, "2026-09": -9_000}
    monkeypatch.setattr(
        insights,
        "off_budget_lines",
        lambda _conn, months: [Line("twint-particuliers", "variable", nets[months[0]], 2)],
    )
    with year.engine().connect() as conn:
        found = [
            a for a in sentinels.evaluate(conn, date(2026, 10, 27)) if a.kind == "off_budget_up"
        ]
    assert [a.key for a in found] == ["off-budget-up:twint-particuliers:2026-10"]
    assert "CHF" not in found[0].notice
    nets["2026-09"] = -4_000  # la hausse s'arrête : rien
    with year.engine().connect() as conn:
        assert not [
            a for a in sentinels.evaluate(conn, date(2026, 10, 27)) if a.kind == "off_budget_up"
        ]
