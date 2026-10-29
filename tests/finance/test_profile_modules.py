"""Le pilier 3a suit le pays du profil (chantier « hub générique », G1)."""

from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient

from hub.core import profile
from hub.core.context import HubContext
from hub.domains.finance.classement.app import sentinels
from hub.domains.finance.domain import FinanceDomain
from tests.finance.test_app_reads import (  # noqa: F401 - fixtures
    client,
    ctx,
    fin,
    year,
)
from tests.finance.test_finance_api import token
from tests.finance.test_tools import call

NOVEMBER = date(2026, 11, 15)


def margin_alerts(domain: FinanceDomain, **opts: object) -> int:
    with domain.engine().connect() as conn:
        alerts = sentinels.evaluate(conn, NOVEMBER, **opts)  # type: ignore[arg-type]
    return sum(a.kind == "pillar3a_margin" for a in alerts)


def test_pillar3a_follows_the_country(
    client: TestClient,  # noqa: F811
    ctx: HubContext,  # noqa: F811
    year: FinanceDomain,  # noqa: F811
) -> None:
    kpis = "/api/finance/kpis?month=2026-10"
    assert year.pillar3a()["pillar3a"] is True
    assert client.get(kpis, headers=token(ctx, "aggregates")).json()["pillar3a"] is not None
    assert margin_alerts(year, **year.pillar3a()) == 1

    with ctx.core.engine.begin() as conn:
        profile.update(conn, "system:test", country="FR")
    assert year.pillar3a()["pillar3a"] is False
    assert client.get(kpis, headers=token(ctx, "aggregates")).json()["pillar3a"] is None
    assert call(client, token(ctx, "brain=finance"), "finance_networth")["pillar3a"] is None
    assert margin_alerts(year, **year.pillar3a()) == 0
