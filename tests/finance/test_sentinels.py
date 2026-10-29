"""Lot 7 : sentinelles de nuit (budget, abonnements, 3a) et leurs notifications."""

from __future__ import annotations

import re
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from hub.core import proposals
from hub.core.context import HubContext
from hub.core.notify import Message
from hub.domains.finance.classement.app import sentinels
from hub.domains.finance.domain import FinanceDomain
from hub.platform.db import begin_immediate
from tests.finance.test_app_reads import (  # noqa: F401 - fixtures
    client,
    ctx,
    fin,
    set_budget,
    year,
)
from tests.finance.test_finance_api import app_session, token

TODAY = date(2026, 10, 27)


def kinds(alerts: list[sentinels.Alert]) -> dict[str, str]:
    return {a.key: a.kind for a in alerts}


def test_budget_projection(year: FinanceDomain) -> None:
    set_budget(year, "restaurants", 8_000)  # 80.00 dépensés le 27 : 92.59 projetés
    with year.engine().connect() as conn:
        p = {x.category: x for x in sentinels.budget_projection(conn, "2026-10", TODAY)}
        early = {
            x.category: x for x in sentinels.budget_projection(conn, "2026-10", date(2026, 10, 3))
        }
        past = {x.category: x for x in sentinels.budget_projection(conn, "2026-09", TODAY)}
    assert p["restaurants"].spent == 8_000
    assert p["restaurants"].projected == 8_000 * 31 // 27
    assert p["restaurants"].likely_over
    assert not p["restaurants"].over
    assert p["alimentation"].over  # 300 pour une cible de 250
    assert not p["logement"].over
    assert p["logement"].projected == 150_000
    assert early["restaurants"].projected == early["restaurants"].spent  # trop tôt
    assert not past["restaurants"].likely_over  # mois passé : pas de projection


def test_alerts_are_raised_once_and_notified(
    year: FinanceDomain, ctx: HubContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    set_budget(year, "restaurants", 8_000)
    first = year.run_sentinels()
    assert kinds(first) == {
        "budget-over:alimentation:2026-10": "budget_over",
        "budget-likely:restaurants:2026-10": "budget_likely",
    }
    assert year.run_sentinels() == []  # même occasion : rien de nouveau
    sent: list[Message] = []
    monkeypatch.setattr(ctx.notifier, "send", lambda msg: sent.append(msg) is None)
    synced = proposals.sync_events(ctx)
    assert synced["notified"] == 2
    assert "Budget : une cible du mois est dépassée" in [m.title for m in sent]
    for m in sent:  # rien de financier ne part vers ntfy : ni montant, ni catégorie
        assert not re.search(r"\d", m.title + m.body)
        assert "Alimentation" not in m.title
        assert "Restaurants" not in m.title
        # toucher la notification ouvre l'alerte : un identifiant opaque, pas la catégorie
        assert re.fullmatch(r"/#alert=[0-9a-f]{20}", m.click)
        assert "alimentation" not in m.click
    ids = {sentinels.alert_id(a.key) for a in first}
    assert {m.click.removeprefix("/#alert=") for m in sent} == ids
    assert proposals.sync_events(ctx)["notified"] == 0


def test_recurring_increase(year: FinanceDomain) -> None:
    year.refresh_snapshots(force=True)
    with begin_immediate(year.engine()) as conn:
        key = conn.execute(text("SELECT key FROM recurring ORDER BY key LIMIT 1")).scalar_one()
        conn.execute(
            text("UPDATE recurring SET last_minor = amount_minor - 500 WHERE key = :k"),
            {"k": key},
        )
        raised = sentinels.evaluate(conn, TODAY)
    up = [a for a in raised if a.kind == "recurring_up"]
    assert len(up) == 1
    assert up[0].key.startswith(f"recurring-up:{key}:")
    assert up[0].notice == "Un abonnement a augmenté"


def test_pillar3a_in_november(year: FinanceDomain) -> None:
    with year.engine().connect() as conn:
        assert not [a for a in sentinels.evaluate(conn, TODAY) if a.kind == "pillar3a_margin"]
        nov = [
            a for a in sentinels.evaluate(conn, date(2026, 11, 15)) if a.kind == "pillar3a_margin"
        ]
        full = [
            a
            for a in sentinels.evaluate(conn, date(2026, 11, 15), pillar3a_cap=600_000)
            if a.kind == "pillar3a_margin"
        ]
    assert nov[0].key == "pillar3a:2026-11"
    assert nov[0].detail["margin"]["display"] == "1258.00"
    assert full == []  # tout versé


def test_alerts_route(client: TestClient, ctx: HubContext, year: FinanceDomain) -> None:
    year.nightly()
    assert client.get("/api/finance/alerts", headers=token(ctx, "aggregates")).status_code == 403
    items = client.get("/api/finance/alerts", headers=token(ctx, "brain=finance")).json()["items"]
    assert [i["kind"] for i in items] == ["budget_over"]
    assert items[0]["title"] == "Budget Alimentation dépassé"
    assert items[0]["detail"]["spent"]["display"] == "300.00"
    app_session(ctx, client)
    assert len(client.get("/api/finance/alerts").json()["items"]) == 1
