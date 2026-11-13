"""Frais courants des fonds (migration 0029) : TER saisi par proposition, coût par an et sur
trente ans ; un fonds sans TER reste « frais inconnus », hors des totaux."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient

from hub.core.context import HubContext
from hub.core.errors import Problem
from hub.domains.finance.domain import FinanceDomain
from hub.domains.finance.patrimoine.app import fees
from tests.finance.test_allocation import ON, REAL, setup
from tests.finance.test_double_sas import accept, client, create, ctx, fin
from tests.finance.test_finance_api import token
from tests.finance.test_wealth import WORLD

__all__ = ["client", "ctx", "fin"]  # fixtures


def read(client: TestClient, ctx: HubContext) -> dict[str, Any]:
    r = client.get("/api/finance/fees", headers=token(ctx, "brain=finance"))
    assert r.status_code == 200
    return dict(r.json())


def test_fees_of_held_funds(
    client: TestClient, ctx: HubContext, fin: FinanceDomain, monkeypatch: pytest.MonkeyPatch
) -> None:
    setup(fin)  # WORLD (etf), REAL (fund), une action et une crypto : seuls les fonds comptent
    monkeypatch.setattr(fin, "today", lambda: date.fromisoformat(ON))
    out = read(client, ctx)
    items = {i["isin"]: i for i in out["items"]}
    assert set(items) == {WORLD, REAL}
    assert all(i["ter_pct"] is None and i["yearly_cost"] is None for i in items.values())
    assert out["yearly_cost"]["minor"] == 0
    world = items[WORLD]["value"]["minor"]
    assert out["unknown_value"]["minor"] == world + items[REAL]["value"]["minor"]

    p = create(ctx, "set_fund_fee", {"isin": WORLD, "ter_pct": "0.2"})
    assert p.preview["summary"].endswith(": 0.2 % par an")
    accept(ctx, p)
    out = read(client, ctx)
    item = next(i for i in out["items"] if i["isin"] == WORLD)
    assert (item["ter_pct"], item["source"]) == ("0.2", "user")
    yearly = int((Decimal(world) * Decimal("0.002")).quantize(Decimal(1)))
    assert item["yearly_cost"]["minor"] == yearly == out["yearly_cost"]["minor"]
    assert out["covered_value"]["minor"] == world
    assert out["cost_over_years"]["minor"] == fees.cost_over(world, Decimal("0.002"))
    assert (out["years"], out["assumed_return_pct"]) == (30, "5")
    # la dernière saisie fait foi
    accept(ctx, create(ctx, "set_fund_fee", {"isin": WORLD, "ter_pct": "0.07"}))
    out = read(client, ctx)
    assert next(i for i in out["items"] if i["isin"] == WORLD)["ter_pct"] == "0.07"


def test_refusals(ctx: HubContext, fin: FinanceDomain) -> None:
    setup(fin)
    with pytest.raises(Problem):
        create(ctx, "set_fund_fee", {"isin": "XX0000000000", "ter_pct": "0.2"})
    with pytest.raises(Problem):
        create(ctx, "set_fund_fee", {"isin": WORLD, "ter_pct": "7"})
    accept(ctx, create(ctx, "set_fund_fee", {"isin": WORLD, "ter_pct": "0.2"}))
    with pytest.raises(Problem):
        create(ctx, "set_fund_fee", {"isin": WORLD, "ter_pct": "0.20"})  # aucun changement


def test_cost_over_thirty_years() -> None:
    # 10 000 à 5 % par an : 43 219 sans frais ; à 1 % de frais (4 %), 32 434 : 10 785 de moins
    assert fees.cost_over(1_000_000, Decimal("0.01")) == 1_078_545
    assert fees.cost_over(1_000_000, Decimal(0)) == 0
