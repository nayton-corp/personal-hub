"""Ce que demandent les pages Patrimoine de l'app : événements de la courbe, cours d'un actif,
montant visé d'un compte."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from fastapi.testclient import TestClient

from hub.core.context import HubContext
from hub.core.errors import Problem
from hub.domains.finance.domain import FinanceDomain
from hub.domains.finance.registre.app import catalog
from hub.platform.db import begin_immediate
from tests.finance.test_double_sas import accept, client, create, ctx, fin, ready_account
from tests.finance.test_finance_api import token
from tests.finance.test_performance import FUND, banks, chf, entry, price, ref, run, trade

__all__ = ["banks", "client", "ctx", "fin"]  # fixtures


@pytest.fixture
def saver(fin: FinanceDomain, banks: Any) -> catalog.Account:
    """Les comptes bancaires de `banks`, plus un compte de titres où l'on verse 2000 CHF."""
    acc = ref(fin, "test:titres", "securities")
    with begin_immediate(fin.engine()) as conn:
        price(conn, "2026-01-01", "100")
        trade(conn, acc, "2026-01-10", "20", 200_000)
        entry(conn, acc, "2026-01-20", 1_500, code="VIAC/INCOME/INTEREST")
    return acc


def kinds(out: dict[str, Any]) -> list[tuple[str, str, int]]:
    return [(e["on_date"], e["kind"], chf(e["amount"])) for e in out["events"]]


def test_events_follow_the_saving_not_the_salary(fin: FinanceDomain, saver: Any) -> None:
    # tout le patrimoine : le versement sur les titres et le revenu, pas le salaire ni les dépenses
    assert kinds(run(fin, "2026-01-31")) == [
        ("2026-01-10", "in", 200_000),
        ("2026-01-20", "income", 1_500),
    ]


def test_a_bank_account_alone_has_no_event(fin: FinanceDomain, banks: Any) -> None:
    bcf, _savings = banks
    # salaire et dépenses ne sont pas des événements de l'épargne
    assert kinds(run(fin, "2026-01-31", [f"{bcf.id}|cash"])) == []


def test_prices_route(
    client: TestClient,
    ctx: HubContext,
    fin: FinanceDomain,
    saver: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with begin_immediate(fin.engine()) as conn:
        price(conn, "2026-01-15", "104.5")
    monkeypatch.setattr(fin, "today", lambda: date(2026, 1, 31))
    h = token(ctx, "brain=finance")
    body = client.get("/api/finance/prices", params={"isin": FUND}, headers=h).json()
    assert body["name"] == "Fonds test"
    assert body["currency"] == "CHF"
    assert body["items"] == [
        {"on_date": "2026-01-01", "price": "100"},
        {"on_date": "2026-01-15", "price": "104.5"},
    ]
    later = client.get(
        "/api/finance/prices", params={"isin": FUND, "from": "2026-01-02"}, headers=h
    ).json()
    assert [x["on_date"] for x in later["items"]] == ["2026-01-15"]
    none = client.get("/api/finance/prices", params={"isin": "XX0000000000"}, headers=h).json()
    assert (none["name"], none["items"]) == (None, [])


def test_account_target(client: TestClient, ctx: HubContext, fin: FinanceDomain) -> None:
    a = ready_account(fin)
    h = token(ctx, "brain=finance")
    (before,) = client.get("/api/finance/accounts", headers=h).json()["items"]
    assert before["target"] is None
    p = create(ctx, "edit_account", {"account_id": a.id, "target": 15_000})
    assert p.preview["summary"].endswith(": montant visé 15'000")
    accept(ctx, p)
    (after,) = client.get("/api/finance/accounts", headers=h).json()["items"]
    assert chf(after["target"]) == 1_500_000
    q = create(ctx, "edit_account", {"account_id": a.id, "target": 0})
    assert q.preview["details"]["changes"] == {"target_minor": None}
    accept(ctx, q)
    (gone,) = client.get("/api/finance/accounts", headers=h).json()["items"]
    assert gone["target"] is None
    with pytest.raises(Problem):
        create(ctx, "edit_account", {"account_id": a.id, "target": -5})
