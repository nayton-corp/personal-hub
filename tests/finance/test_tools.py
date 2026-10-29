"""Lot 7 : les seize outils Finance de l'assistant, par les routes `/api/tools`.

Le jeton « brain » lit tout et propose ; le jeton « agrégats » ne voit que des totaux.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from hub.core import proposals
from hub.core.context import HubContext
from hub.core.settings import Auth
from hub.domains.finance.domain import FinanceDomain
from hub.domains.finance.tools import FinanceTools
from tests.conftest import add_connections
from tests.factories.camt import IBAN
from tests.finance.test_app_reads import (  # noqa: F401 - fixtures
    client,
    ctx,
    fin,
    year,
)
from tests.finance.test_finance_api import app_session, token

AGGREGATE_TOOLS = {
    "finance_list_accounts",
    "finance_data_freshness",
    "finance_list_categories",
    "finance_month_summary",
    "finance_budget_status",
    "finance_category_trend",
    "finance_networth",
}


def call(client: TestClient, headers: dict[str, str], name: str, **args: Any) -> Any:
    r = client.post(f"/api/tools/finance/{name}", headers=headers, json=args)
    assert r.status_code == 200, r.text
    return r.json()["result"]


def test_capabilities_by_token(client: TestClient, ctx: HubContext) -> None:
    brain = client.get("/api/tools", headers=token(ctx, "brain")).json()["domains"]
    assert [d["domain"] for d in brain] == ["finance"]
    assert len(brain[0]["tools"]) == 16
    assert brain[0]["aggregates_only"] is False
    agg = client.get("/api/tools", headers=token(ctx, "aggregates")).json()["domains"]
    assert set(agg[0]["tools"]) == AGGREGATE_TOOLS
    assert agg[0]["aggregates_only"] is True
    listed = client.get("/api/tools/finance", headers=token(ctx, "aggregates")).json()
    assert {t["name"] for t in listed["items"]} == AGGREGATE_TOOLS
    # aucun outil pour un jeton collecteur, et l'app n'utilise pas ces routes
    assert client.get("/api/tools", headers=token(ctx, "collector")).json()["domains"] == []
    assert client.get("/api/tools/finance", headers=token(ctx, "collector")).status_code == 403
    app_session(ctx, client)
    assert client.get("/api/tools").status_code == 403


def test_category_is_a_closed_list(
    client: TestClient, ctx: HubContext, year: FinanceDomain
) -> None:
    items = client.get("/api/tools/finance", headers=token(ctx, "brain")).json()["items"]
    schema = next(t for t in items if t["name"] == "finance_propose_category")["input_schema"]
    assert "restaurants" in schema["properties"]["category"]["enum"]
    r = client.post(
        "/api/tools/finance/finance_propose_category",
        headers=token(ctx, "brain"),
        json={"entry_id": "e01", "category": "casino"},
    )
    assert r.status_code == 422
    r = client.post(
        "/api/tools/finance/finance_month_summary",
        headers=token(ctx, "brain"),
        json={"month": "2026-10", "extra": 1},
    )
    assert r.status_code == 422
    assert (
        client.post("/api/tools/finance/inconnu", headers=token(ctx, "brain"), json={}).status_code
        == 404
    )


def test_restaurants_this_month(client: TestClient, ctx: HubContext, year: FinanceDomain) -> None:
    """La sortie du lot 7 : « combien en restaurants ce mois ? »."""
    out = call(client, token(ctx, "brain"), "finance_month_summary")
    assert out["month"] == "2026-10"
    assert out["data_as_of"] == "2026-10-25"
    resto = next(c for c in out["by_category"] if c["category"] == "restaurants")
    assert resto == {
        "category": "restaurants",
        "name": "Restaurants et sorties",
        "group": "variable",
        "amount": "80.00",
        "direction": "debit",
        "count": 1,
    }
    assert out["income"] == "5020.00"
    # agrégats : une catégorie d'une seule écriture est fondue dans « autres »
    agg = call(client, token(ctx, "aggregates"), "finance_month_summary", month="2026-10")
    assert "restaurants" not in {c["category"] for c in agg["by_category"]}
    assert "autres" in {c["category"] for c in agg["by_category"]}
    trend = call(client, token(ctx, "aggregates"), "finance_category_trend", category="restaurants")
    assert all(p["amount"] is None for p in trend["series"] if p["count"])
    full = call(client, token(ctx, "brain"), "finance_category_trend", category="restaurants")
    assert full["series"][-1] == {"month": "2026-10", "amount": "80.00", "count": 1}
    r = client.post(
        "/api/tools/finance/finance_month_summary",
        headers=token(ctx, "brain"),
        json={"month": "2026-12"},
    )
    assert r.status_code == 422


def test_aggregates_never_reach_entries(
    client: TestClient, ctx: HubContext, year: FinanceDomain
) -> None:
    agg = token(ctx, "aggregates")
    for name, args in [
        ("finance_search", {"query": "bistrot"}),
        ("finance_to_review", {}),
        ("finance_recurring", {}),
        ("finance_propose_category", {"entry_id": "e01", "category": "divers"}),
        ("finance_proposal_status", {"proposal_id": "0123456789"}),
    ]:
        r = client.post(f"/api/tools/finance/{name}", headers=agg, json=args)
        assert r.status_code == 403, name
    seen = json.dumps(
        [call(client, agg, n) for n in sorted(AGGREGATE_TOOLS - {"finance_category_trend"})]
    )
    assert IBAN not in seen
    assert IBAN[:4] + " " not in seen
    assert "Bistrot" not in seen
    assert "Kiosque" not in seen


def test_reads_for_the_local_model(
    client: TestClient, ctx: HubContext, year: FinanceDomain
) -> None:
    add_connections(ctx, "bcf", "viac")
    brain = token(ctx, "brain")
    accounts = call(client, brain, "finance_list_accounts")["accounts"]
    assert accounts[0]["name"] == "Compte privé"
    assert "iban" not in accounts[0]
    fresh = call(client, brain, "finance_data_freshness")
    assert fresh["sources"][0]["last_statement"] == "2026-10-25"
    assert {c["collector"] for c in fresh["collectors"]} >= {"bcf", "viac"}
    budget = call(client, brain, "finance_budget_status")
    assert budget["over"] == ["Alimentation"]
    food = next(x for x in budget["lines"] if x["category"] == "alimentation")
    assert food["spent"] == "300.00"
    assert food["target"] == "250.00"
    worth = call(client, brain, "finance_networth")
    assert worth["pillar3a"]["paid"] == "6000.00"
    found = call(client, brain, "finance_search", query="bistrot", month="2026-10")
    assert [i["amount"] for i in found["items"]] == ["-80.00"]
    assert found["items"][0]["category"] == "restaurants"
    assert "tiers" in found["external_text"]
    review = call(client, brain, "finance_to_review")
    merchants = {g["counterparty"]: g for g in review["groups"]}
    assert merchants["kiosque inconnu"]["known_merchant"] is False
    assert "bistrot fictif" in FinanceTools(year).known_merchants(year.engine().connect())
    assert call(client, brain, "finance_recurring")["count"] >= 1
    cats = call(client, brain, "finance_list_categories")["categories"]
    assert {"id": "restaurants", "name": "Restaurants et sorties", "group": "variable"} in cats


def test_proposals_need_a_card(client: TestClient, ctx: HubContext, year: FinanceDomain) -> None:
    brain = token(ctx, "brain")
    entry = call(client, brain, "finance_search", query="kiosque")["items"][0]["entry_id"]
    out = call(
        client,
        brain,
        "finance_propose_category",
        entry_id=entry,
        category="loisirs",
        reason="Un kiosque vend des journaux.",
    )
    assert out["status"] == "pending"
    assert out["created"] is True
    with ctx.core.engine.connect() as conn:
        p = proposals.get(conn, out["proposal_id"])
    assert p.tier == "human"
    assert p.params["suggested"] is True
    assert p.reason == "Un kiosque vend des journaux."
    status = call(client, brain, "finance_proposal_status", proposal_id=out["proposal_id"])
    assert status["status"] == "pending"
    budget = call(client, brain, "finance_propose_budget", category="restaurants", amount="120.5")
    with ctx.core.engine.connect() as conn:
        assert proposals.get(conn, budget["proposal_id"]).params["monthly_minor"] == 12050
    yearly = call(
        client, brain, "finance_propose_budget", category="voyages", amount="1200", cadence="year"
    )
    with ctx.core.engine.connect() as conn:
        p = proposals.get(conn, yearly["proposal_id"])
    assert (p.params["monthly_minor"], p.params["cadence"]) == (10000, "year")
    assert "par an" in p.preview["summary"]
    r = client.post(
        "/api/tools/finance/finance_propose_budget",
        headers=brain,
        json={"category": "salaire", "amount": "10"},
    )
    assert r.status_code == 422
    many = call(
        client, brain, "finance_propose_categories", entry_ids=[entry], category="alimentation"
    )
    with ctx.core.engine.connect() as conn:
        p = proposals.get(conn, many["proposal_id"])
    assert p.kind == "categorize_entries"
    assert p.params == {"entry_ids": [entry], "category_id": "alimentation", "suggested": True}
    page = call(client, brain, "finance_to_review", limit=1, offset=1)
    assert len(page["groups"]) <= 1
    rule = call(client, brain, "finance_propose_rule", keyword="Kiosque", category="loisirs")
    with ctx.core.engine.connect() as conn:
        assert proposals.get(conn, rule["proposal_id"]).params["pattern"] == "kiosque"
    note = call(client, brain, "finance_propose_note", entry_id=entry, note="journal du dimanche")
    assert note["kind"] == "add_note"
    r = client.post(
        "/api/tools/finance/finance_proposal_status",
        headers=brain,
        json={"proposal_id": "01INCONNU000000000000"},
    )
    assert r.status_code == 404


def test_proposals_are_rate_limited(
    client: TestClient, ctx: HubContext, year: FinanceDomain
) -> None:
    ctx.settings = ctx.settings.model_copy(update={"auth": Auth(token_proposals_per_hour=2)})
    brain = token(ctx, "brain")
    for category in ("loisirs", "divers"):
        call(client, brain, "finance_propose_budget", category=category, amount="10")
    r = client.post(
        "/api/tools/finance/finance_propose_budget",
        headers=brain,
        json={"category": "shopping", "amount": "10"},
    )
    assert r.status_code == 429
    assert r.json()["type"] == "rate_limited"


@pytest.mark.parametrize(
    ("value", "expected"), [("12", 1200), ("12.5", 1250), ("12.50", 1250), (12, 1200), ("0", 0)]
)
def test_budget_amounts_without_float(
    client: TestClient, ctx: HubContext, year: FinanceDomain, value: object, expected: int
) -> None:
    out = call(
        client, token(ctx, "brain"), "finance_propose_budget", category="loisirs", amount=value
    )
    with ctx.core.engine.connect() as conn:
        assert proposals.get(conn, out["proposal_id"]).params["monthly_minor"] == expected


def test_budget_accepts_the_former_amount_name(
    client: TestClient, ctx: HubContext, year: FinanceDomain
) -> None:
    out = call(
        client, token(ctx, "brain"), "finance_propose_budget", category="loisirs", amount_chf="7"
    )
    with ctx.core.engine.connect() as conn:
        assert proposals.get(conn, out["proposal_id"]).params["monthly_minor"] == 700
