"""Contrats de sortie des routes Finance (audit M10) : chaque route déclare son modèle, et sur
un jeu de données qui touche à tout (relevé bancaire, budget, dette, cryptos, titres), aucune
réponse ne porte un champ que son modèle ne déclare pas."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy import text
from starlette.routing import compile_path

from hub.core.context import HubContext
from hub.domains.finance.domain import FinanceDomain
from tests.finance.test_crypto_cost import setup as crypto_setup
from tests.finance.test_double_sas import accept, create
from tests.finance.test_finance_api import (  # noqa: F401 (fixtures)
    app_session,
    client,
    ctx,
    fin,
    loaded,
    token,
)

LENDER = "Banque Fictive"


def _walk(routes: list[Any], prefix: str) -> list[tuple[str, APIRoute]]:
    """Les routes avec leur chemin complet ; un routeur inclus porte son préfixe."""
    out: list[tuple[str, APIRoute]] = []
    for r in routes:
        if isinstance(r, APIRoute):
            out.append((prefix + r.path, r))
        elif hasattr(r, "original_router"):  # fastapi.routing._IncludedRouter
            out += _walk(r.original_router.routes, prefix + r.include_context.prefix)
    return out


def finance_routes(http: TestClient) -> list[tuple[str, APIRoute]]:
    found = _walk(http.app.routes, "")  # type: ignore[attr-defined]
    return [(path, r) for path, r in found if path.startswith("/api/finance/")]


def extras(value: Any, path: str = "") -> list[str]:
    """Les chemins où une réponse validée porte des champs hors modèle."""
    found: list[str] = []
    if isinstance(value, BaseModel):
        for k in value.__pydantic_extra__ or {}:
            found.append(f"{path}.{k}")
        for name in type(value).model_fields:
            found += extras(getattr(value, name), f"{path}.{name}")
    elif isinstance(value, list):
        for i, x in enumerate(value):
            found += extras(x, f"{path}[{i}]")
    elif isinstance(value, dict):
        for k, x in value.items():
            found += extras(x, f"{path}[{k}]")
    return found


def test_every_finance_route_declares_its_output(client: TestClient) -> None:  # noqa: F811
    routes = finance_routes(client)
    assert len(routes) >= 30
    missing = [
        f"{sorted(r.methods)} {path}"
        for path, r in routes
        if r.response_model is None and not path.endswith(".csv")
    ]
    assert missing == []


@pytest.fixture
def everything(ctx: HubContext, fin: FinanceDomain, loaded: FinanceDomain) -> FinanceDomain:  # noqa: F811
    accept(
        ctx,
        create(
            ctx,
            "set_budget",
            {"category_id": "alimentation", "amount_minor": 40_000, "cadence": "month"},
        ),
    )
    accept(
        ctx,
        create(
            ctx,
            "save_debt",
            {
                "name": "Prêt",
                "lender": LENDER,
                "kind": "loan",
                "balance_minor": 500_000,
                "balance_on": "2026-10-01",
                "payment_minor": 35_000,
                "rate_pct": "2.5",
            },
        ),
    )
    crypto_setup(fin)
    return fin


CALLS = [
    "/accounts",
    "/accounts/pending",
    "/kpis",
    "/kpis?month=2026-10",
    "/holdings",
    "/debts",
    "/breaks",
    "/lookthrough",
    "/lookthrough?dimension=holding",
    "/lookthrough?dimension=currency",
    "/transfers",
    "/networth/history",
    "/networth/history?from=2026-09-01&step=week",
    "/performance",
    "/performance?step=month",
    "/prices?isin=BTC",
    "/entries",
    "/entries?uncategorized=true&sort=amount",
    "/trades?isin=BTC",
    "/search?q=jean",
    "/categories",
    "/freshness",
    "/settings",
    "/summary",
    "/budget",
    "/budget?period=q",
    "/budget/totals",
    "/budget/months",
    "/flows",
    "/trend?category=alimentation",
    "/review",
    "/rules/packs",
    "/recurring",
]


def test_an_empty_instance_answers_every_route(client: TestClient, ctx: HubContext) -> None:  # noqa: F811
    """Sans donnée, chaque route répond dans sa forme (un champ vide est `null`, pas une 500)."""
    headers = token(ctx, "brain=finance")
    for call in CALLS:
        r = client.get(f"/api/finance{call}", headers=headers)
        assert r.status_code == 200, (call, r.text)


def test_responses_carry_no_field_outside_their_model(
    client: TestClient,  # noqa: F811
    ctx: HubContext,  # noqa: F811
    everything: FinanceDomain,
) -> None:
    headers = token(ctx, "brain=finance")
    routes = [(p, r) for p, r in finance_routes(client) if "GET" in r.methods]
    first = client.get("/api/finance/entries", headers=headers).json()["items"][0]["id"]
    calls = [*CALLS, f"/entries/{first}"]
    with everything.engine().connect() as conn:
        import_id = conn.execute(text("SELECT id FROM imports")).scalar()
    calls.append(f"/imports/{import_id}")  # réservé à l'app : la session passkey, posée après
    strays: list[str] = []
    for call in calls:
        if call.startswith("/imports/"):
            app_session(ctx, client)
            headers = {}
        r = client.get(f"/api/finance{call}", headers=headers)
        assert r.status_code == 200, (call, r.text)
        path = "/api/finance" + call.split("?")[0]
        model = next(r.response_model for p, r in routes if compile_path(p)[0].match(path))
        assert model is not None, call
        strays += [f"{call}{x}" for x in extras(model.model_validate(r.json()))]
    assert strays == []
