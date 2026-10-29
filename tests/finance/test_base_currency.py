"""Devise de base de l'instance (chantier « hub générique », G1b) : `HUB_CURRENCY`, fixée dans
`finance.db` à sa création ; un hub en euros valorise, budgète et convertit en euros."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import text

from hub.domains.finance import catalog, handlers, insights, market, valuation
from hub.domains.finance.domain import MIGRATIONS, CurrencyMismatch, FinanceDomain
from hub.domains.finance.importer import Incoming
from hub.kernel.money import CurrencyError, base_currency
from hub.platform import migrations as runner
from hub.platform.db import begin_immediate
from tests.finance.conftest import finance_settings, open_account


def test_base_currency_comes_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HUB_CURRENCY", raising=False)
    assert base_currency() == "CHF"
    monkeypatch.setenv("HUB_CURRENCY", "eur")
    assert base_currency() == "EUR"
    monkeypatch.setenv("HUB_CURRENCY", "XYZ")
    with pytest.raises(CurrencyError):
        base_currency()


def test_a_new_base_keeps_its_currency(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HUB_CURRENCY", "EUR")
    domain = FinanceDomain(finance_settings(tmp_path))
    domain.migrate()
    assert domain.recorded_currency() == "EUR"
    assert domain.health().ok
    monkeypatch.setenv("HUB_CURRENCY", "CHF")
    assert domain.health().db == "currency_mismatch"
    with pytest.raises(CurrencyMismatch, match="HUB_CURRENCY=EUR"):
        domain.migrate()
    domain.engine().dispose()


def test_an_existing_ledger_stays_in_francs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Une base d'avant la révision 0010 qui a des écritures a été tenue en CHF."""
    domain = FinanceDomain(finance_settings(tmp_path))
    runner.upgrade(MIGRATIONS, domain.path, "0009_rule_packs")
    with begin_immediate(domain.engine()) as conn:
        a = catalog.add_account(
            conn, institution="BCF", name="Privé", currency="CHF", external_ref="bcf:1"
        )
    open_account(domain, a, "2026-09-30", 100_000)
    monkeypatch.setenv("HUB_CURRENCY", "EUR")
    with pytest.raises(CurrencyMismatch):
        domain.migrate()
    assert domain.recorded_currency() == "CHF"
    domain.engine().dispose()


@pytest.fixture
def euro(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FinanceDomain:
    monkeypatch.setenv("HUB_CURRENCY", "EUR")
    domain = FinanceDomain(finance_settings(tmp_path))
    domain.migrate()
    yield domain  # type: ignore[misc]
    domain.engine().dispose()


def test_a_euro_hub_values_in_euros(euro: FinanceDomain) -> None:
    with begin_immediate(euro.engine()) as conn:
        eur = catalog.add_account(conn, institution="Banque", name="Courant", external_ref="fr:1")
        chf = catalog.add_account(
            conn, institution="Banque", name="Suisse", currency="CHF", external_ref="ch:1"
        )
    assert eur.currency == "EUR"
    open_account(euro, eur, "2026-10-01", 50_000)
    open_account(euro, chf, "2026-10-01", 10_000)
    with euro.engine().connect() as conn:
        assert valuation.value_at(conn, "2026-10-27").missing_fx == [chf.id]
    fx = {"on_date": "2026-10-01", "base": "CHF", "quote": "EUR", "rate": "1.05", "source": "ecb"}
    doc = {"format": market.FORMAT, "fetched_at": "2026-10-27T07:00:00Z", "fx": [fx]}
    euro.importer.process([Incoming("fx.json", json.dumps(doc).encode())])
    with euro.engine().connect() as conn:
        v = valuation.value_at(conn, "2026-10-27")
        assert (v.net_worth, v.missing_fx) == (60_500, [])
        kpis = insights.kpis(conn, "2026-10", date(2026, 10, 27), pillar3a=False)
    assert kpis["currency"] == "EUR"
    assert kpis["net_worth"] == {"minor": 60_500, "currency": "EUR", "display": "605.00"}


def test_a_budget_is_in_the_base_currency(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HUB_CURRENCY", "EUR")
    assert handlers.SetBudget(category_id="loisirs", monthly_minor=1).currency == "EUR"
    with pytest.raises(ValidationError):
        handlers.SetBudget(category_id="loisirs", monthly_minor=1, currency="CHF")


def test_rows_of_a_euro_hub(euro: FinanceDomain) -> None:
    with euro.engine().connect() as conn:
        assert conn.execute(text("SELECT code FROM base_currency")).scalar_one() == "EUR"
