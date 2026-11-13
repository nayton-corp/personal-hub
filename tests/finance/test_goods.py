"""Biens hors comptes (migration 0028) : création, valeur saisie, variation annuelle, clôture ;
le patrimoine les compte, le rendement les ignore, et rien ne change sans bien."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient

from hub.core.context import HubContext
from hub.core.errors import Problem
from hub.domains.finance.domain import FinanceDomain
from hub.domains.finance.patrimoine.app import goods, valuation
from tests.factories.camt import Tx
from tests.finance.conftest import ready_account
from tests.finance.test_double_sas import accept, client, create, ctx, fin, load
from tests.finance.test_finance_api import token

__all__ = ["client", "ctx", "fin"]  # fixtures


@pytest.fixture
def funded(fin: FinanceDomain, monkeypatch: pytest.MonkeyPatch) -> FinanceDomain:
    monkeypatch.setattr(fin, "today", lambda: date(2026, 10, 31))
    ready_account(fin)
    load(fin, [Tx("5000.00", False, date(2026, 10, 1), counterparty="Employeur Fictif")])
    return fin


def save(ctx: HubContext, params: dict[str, Any]) -> dict[str, Any]:
    out = accept(ctx, create(ctx, "save_good", params))
    assert out.result is not None
    return out.result


def listed(client: TestClient, ctx: HubContext) -> list[dict[str, Any]]:
    r = client.get("/api/finance/goods", headers=token(ctx, "brain=finance"))
    assert r.status_code == 200
    return list(r.json()["items"])


def test_a_good_joins_the_net_worth_without_touching_the_return(
    client: TestClient, ctx: HubContext, funded: FinanceDomain
) -> None:
    with funded.engine().connect() as conn:
        before = valuation.value_at(conn, "2026-10-31")
    assert "biens" not in before.by_envelope  # sans bien, les enveloppes sont celles d'avant
    p = create(
        ctx,
        "save_good",
        {
            "name": "Voiture",
            "kind": "vehicle",
            "value_minor": 2_000_000,
            "value_on": "2026-10-10",
            "yearly_change_pct": "-15",
        },
    )
    assert p.preview["summary"] == (
        "Nouveau bien « Voiture » (Véhicule) : 20000.00 CHF au 2026-10-10"
    )
    accept(ctx, p)
    (g,) = listed(client, ctx)
    # 21 jours à -15 % par an : 20000 × 0.85^(21/365)
    expected = int((Decimal(2_000_000) * Decimal("0.85") ** (Decimal(21) / 365)).quantize(1))
    assert g["value"]["minor"] == expected
    assert (g["yearly_change_pct"], g["stated_on"]) == ("-15", "2026-10-10")
    with funded.engine().connect() as conn:
        v = valuation.value_at(conn, "2026-10-31")
        day_before = valuation.value_at(conn, "2026-10-09")
    assert v.by_envelope["biens"] == expected
    assert v.by_account[f"good:{g['id']}"] == expected
    assert v.net_worth == before.net_worth + expected
    # la décote n'est ni un gain ni une perte de placement : le gain reste celui d'avant
    assert v.net_worth - v.deposits == before.net_worth - before.deposits
    assert "biens" not in day_before.by_envelope
    perf = client.get(
        "/api/finance/performance?from=2026-10-01&to=2026-10-31",
        headers=token(ctx, "brain=finance"),
    ).json()
    assert perf["summary"]["gain"]["minor"] == 0
    hist = client.get("/api/finance/networth/history", headers=token(ctx, "brain=finance")).json()
    assert hist["items"][-1]["by_envelope"]["biens"]["minor"] == expected


def test_revalue_edit_and_close(client: TestClient, ctx: HubContext, funded: FinanceDomain) -> None:
    out = save(
        ctx,
        {
            "name": "Appartement",
            "kind": "home",
            "value_minor": 50_000_000,
            "value_on": "2026-10-01",
        },
    )
    gid = out["good_id"]
    assert listed(client, ctx)[0]["value"]["minor"] == 50_000_000  # valeur fixe sans variation
    p = create(
        ctx, "save_good", {"good_id": gid, "value_minor": 52_000_000, "value_on": "2026-10-20"}
    )
    assert "valeur de 520000.00 CHF au 2026-10-20" in p.preview["summary"]
    accept(ctx, p)
    (g,) = listed(client, ctx)
    assert g["value"]["minor"] == 52_000_000
    assert [x["on_date"] for x in g["values"]] == ["2026-10-01", "2026-10-20"]
    save(ctx, {"good_id": gid, "name": "Appartement de Bulle"})
    assert listed(client, ctx)[0]["name"] == "Appartement de Bulle"
    p = create(ctx, "save_good", {"good_id": gid, "closed_on": "2026-10-30"})
    assert p.preview["summary"] == "Bien « Appartement de Bulle » clos au 2026-10-30"
    accept(ctx, p)
    assert listed(client, ctx)[0]["value"]["minor"] == 0
    with funded.engine().connect() as conn:
        assert valuation.value_at(conn, "2026-10-31").by_envelope["biens"] == 0
        assert valuation.value_at(conn, "2026-10-29").by_envelope["biens"] == 52_000_000


def test_refusals(ctx: HubContext, funded: FinanceDomain) -> None:
    for bad in (
        {"name": "Vélo", "kind": "object"},  # sans valeur
        {"name": "Vélo", "kind": "object", "value_minor": 100},  # valeur sans date
        {"good_id": "x", "currency": "EUR"},  # devise hors création
    ):
        with pytest.raises((Problem, ValueError)):
            create(ctx, "save_good", bad)
    with pytest.raises(Problem):
        create(ctx, "save_good", {"good_id": "inconnu", "name": "Vélo"})
    gid = save(
        ctx, {"name": "Vélo", "kind": "object", "value_minor": 100_000, "value_on": "2026-10-01"}
    )["good_id"]
    with pytest.raises(Problem):
        create(ctx, "save_good", {"good_id": gid, "name": "Vélo"})  # aucun changement
    with pytest.raises(Problem):
        create(
            ctx,
            "save_good",
            {
                "name": "Or",
                "kind": "object",
                "currency": "XXX",
                "value_minor": 1,
                "value_on": "2026-10-01",
            },
        )


def test_value_follows_the_yearly_change() -> None:
    g = goods.Good("g", "Voiture", "vehicle", "CHF", Decimal("-0.15"), None)
    book = goods.Book([g], {"g": [("2025-01-01", 1_000_000)]})
    assert book.value(g, "2024-12-31") is None
    assert book.value(g, "2025-01-01") == 1_000_000
    assert book.value(g, "2026-01-01") == 850_000
    fixed = goods.Good("h", "Tableau", "object", "CHF", None, "2026-06-01")
    book = goods.Book([fixed], {"h": [("2025-01-01", 500_000)]})
    assert book.value(fixed, "2026-05-31") == 500_000
    assert book.value(fixed, "2026-06-01") == 0
