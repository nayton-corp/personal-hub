"""Stratégies repérées (migration 0030) : la série d'achats réguliers (règles pures, garde-fous
contre les faux positifs), la carte demandée chaque nuit, le refus retenu, la stratégie validée
qui reprend le journal depuis le premier achat, et le 3a lu au niveau du compte."""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from hub.core import proposal_events, proposals
from hub.core.context import HubContext
from hub.domains.finance.domain import FinanceDomain
from hub.domains.finance.patrimoine.model import regular_buys as rb
from hub.domains.finance.registre.app import ledger
from hub.platform.db import begin_immediate
from tests.finance.conftest import rows
from tests.finance.test_crypto_cost import doc
from tests.finance.test_double_sas import APP, accept, client, ctx, fin
from tests.finance.test_exchange import op
from tests.finance.test_strategies import at, coins, listed
from tests.finance.test_wealth import add_ref

__all__ = ["client", "coins", "ctx", "fin"]  # fixtures

TODAY = date(2026, 11, 14)


def monthly(n: int, amount: int = 20_000, first: date = date(2025, 12, 1)) -> list[rb.Buy]:
    out, d = [], first
    for i in range(n):
        out.append(rb.Buy(d + timedelta(days=i % 3), amount))
        d = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
    return out


# --- les règles, pures ---------------------------------------------------------------------


def test_a_monthly_series_is_found_with_its_day_and_amount() -> None:
    buys = monthly(12)
    s = rb.detect(buys, [], TODAY)
    assert s is not None
    assert (s.cadence, s.day, s.amount, len(s.buys)) == ("monthly", 1, 20_000, 12)
    assert (s.first, s.last) == (date(2025, 12, 1), date(2026, 11, 3))
    # montants à quelques francs près : arrondis, toujours la même série
    near = [rb.Buy(b.on, b.amount + (900 if i % 2 else -800)) for i, b in enumerate(buys)]
    found = rb.detect(near, [], TODAY)
    assert found is not None
    assert found.amount == 20_000
    assert rb.round_amount(19_960) == 20_000
    assert rb.round_amount(4_740) == 4_700


def test_a_weekly_series_is_weekly_not_monthly() -> None:
    weekly = [rb.Buy(date(2026, 9, 7) + timedelta(weeks=i), 5_000) for i in range(10)]
    s = rb.detect(weekly, [], TODAY)
    assert s is not None
    assert (s.cadence, s.day, len(s.buys)) == ("weekly", 0, 10)  # chaque lundi


@pytest.mark.parametrize(
    ("buys", "sold", "why"),
    [
        (monthly(3), [], "trop peu d'achats"),
        (monthly(5, first=date(2025, 6, 1)), [], "série arrêtée"),
        (monthly(8), [date(2026, 5, 10)], "vente pendant la série"),
    ],
)
def test_guards_against_false_positives(buys: list[rb.Buy], sold: list[date], why: str) -> None:
    assert rb.detect(buys, sold, TODAY) is None
    s = rb.Series("monthly", 1, 20_000, tuple(buys))
    assert why in rb.problems(s, sold, TODAY)


def test_amounts_must_stay_close() -> None:
    wild = [rb.Buy(b.on, a) for b, a in zip(monthly(6), (10_000, 30_000) * 3, strict=True)]
    assert rb.detect(wild, [], TODAY) is None
    # une augmentation : la série repart du nouveau montant, assez longue ou rien
    raised = monthly(4, 10_000, date(2025, 12, 1)) + monthly(8, 30_000, date(2026, 4, 1))
    s = rb.detect(raised, [], TODAY)
    assert s is not None
    assert (s.amount, len(s.buys)) == (30_000, 8)
    # le nouveau montant ne dure que trois mois : trop tôt pour parler d'une décision
    short = monthly(9, 10_000, date(2025, 11, 1)) + monthly(3, 30_000, date(2026, 8, 1))
    assert rb.detect(short, [], TODAY) is None


def test_extra_buys_are_tolerated_until_they_dominate() -> None:
    base = monthly(8, first=date(2026, 4, 1))
    treat = [rb.Buy(date(2026, 6, 15), 50_000)]  # un coup de cœur : la série tient
    s = rb.detect(base + treat, [], TODAY)
    assert s is not None
    assert len(s.buys) == 8
    # des achats au hasard toutes les semaines : ce n'est pas une décision mensuelle
    noise = [
        rb.Buy(date(2026, 4, 9) + timedelta(weeks=i), 7_000 + 900 * (i % 5)) for i in range(30)
    ]
    assert rb.detect(base + noise, [], TODAY) is None


def test_same_day_buys_count_once_and_bands_are_wide() -> None:
    split = [rb.Buy(b.on, 10_000) for b in monthly(6, first=date(2026, 6, 1))] * 2
    s = rb.detect(split, [], TODAY)
    assert s is not None
    assert s.amount == 20_000
    assert rb.amount_band(20_000) == rb.amount_band(21_000)
    assert rb.amount_band(20_000) != rb.amount_band(40_000)


# --- la carte de nuit, le refus, la validation ------------------------------------------------


def buy_ops(n: int, first: date, chf: str = "200") -> list[dict[str, Any]]:
    out = []
    d = first
    for i in range(n):
        on = (d + timedelta(days=i % 2)).isoformat()
        out.append(op(f"f{i}", "fiat_deposit", on, ("CHF", chf, "deposit")))
        out.append(op(f"d{i}", "trade", on, ("CHF", f"-{chf}", "trade"), ("BTC", "0.004", "trade")))
        d = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
    return out


def pending(ctx: HubContext) -> list[proposals.Proposal]:
    with ctx.core.engine.connect() as conn:
        ids = conn.execute(
            text("SELECT id FROM proposals WHERE status = 'pending' AND kind = 'save_strategy'")
        ).scalars()
        return [proposals.get(conn, i) for i in list(ids)]


def test_a_dca_is_proposed_once_and_kept_from_its_first_buy(
    client: TestClient, ctx: HubContext, coins: FinanceDomain, monkeypatch: pytest.MonkeyPatch
) -> None:
    coins.importer.process([doc(operations=buy_ops(8, date(2026, 4, 1)))])
    at(coins, monkeypatch, "2026-11-14")
    assert coins.detect_strategies() == 1
    proposal_events.sync_events(ctx)
    (p,) = pending(ctx)
    assert p.created_by == "system:finance"
    assert p.preview["summary"] == "DCA repéré : 200 CHF de Bitcoin chaque mois"
    seen = p.preview["details"]["detected"]
    assert (seen["since"], seen["kept"], len(seen["periods"])) == ("2026-04-01", 8, 8)
    assert (seen["count"], seen["low"], seen["high"]) == (8, 20_000, 20_000)
    assert p.preview["details"]["phrase"] == "Le 1er du mois, j'achète pour 200 CHF de Bitcoin."

    # la nuit suivante : même série, aucune carte de plus
    coins.detect_strategies()
    assert proposal_events.sync_events(ctx)["requested"] == 0
    assert len(pending(ctx)) == 1

    accept(ctx, p)
    (s,) = listed(client, ctx)["items"]
    assert (s["origin"], s["created_on"], s["kept"]) == (
        "detected",
        "2026-04-01",
        {"done": 7, "skipped": 0},
    )
    assert [x["state"] for x in s["steps"]] == ["done"] * 7  # novembre : à la vérification de nuit
    coins.run_strategies()
    (s,) = listed(client, ctx)["items"]
    assert s["kept"] == {"done": 8, "skipped": 0}
    assert s["steps"][0]["key"] == "2026-11"
    # une stratégie d'achat régulier sur la cible : plus rien à proposer
    assert coins.detect_strategies() == 0


def test_a_refused_dca_does_not_come_back(
    ctx: HubContext, coins: FinanceDomain, monkeypatch: pytest.MonkeyPatch
) -> None:
    coins.importer.process([doc(operations=buy_ops(6, date(2026, 6, 1)))])
    at(coins, monkeypatch, "2026-11-14")
    coins.detect_strategies()
    proposal_events.sync_events(ctx)
    (p,) = pending(ctx)
    proposals.reject(ctx, APP, p.id)
    for day in ("2026-11-15", "2026-11-16"):
        at(coins, monkeypatch, day)
        assert coins.detect_strategies() == 1  # le domaine redemande…
        proposal_events.sync_events(ctx)
        assert pending(ctx) == []  # … le cœur ne recrée pas la carte refusée


def test_a_pension_account_is_read_by_its_deposits_not_its_funds(
    ctx: HubContext, fin: FinanceDomain, monkeypatch: pytest.MonkeyPatch
) -> None:
    viac = add_ref(fin, "viac:3.1", "pension", "3a VIAC")
    with begin_immediate(fin.engine()) as conn:
        d = date(2026, 1, 25)
        for i in range(10):
            for code, amount in (("VIAC/DEPOSIT", 60_000), ("VIAC/TRADE/BUY", -59_000)):
                ledger.append_entry(
                    conn,
                    ledger.NewEntry(
                        viac.id, d.isoformat(), amount, "CHF", f"t|{i}|{code}", bank_tx_code=code
                    ),
                )
            ledger.append(
                conn,
                "trades",
                {
                    "account_id": viac.id,
                    "trade_date": d.isoformat(),
                    "isin": "CH0000000011",
                    "quantity": "3",
                    "amount_minor": 59_000,
                    "currency": "CHF",
                    "dedup_key": f"viac|{i}",
                    "import_id": None,
                    "created_at": "2026-01-01T00:00:00.000Z",
                },
            )
            d = (d.replace(day=28) + timedelta(days=4)).replace(day=25)
    at(fin, monkeypatch, "2026-11-14")
    from hub.domains.finance.patrimoine.app import strategy_detect

    with fin.engine().connect() as conn:
        (found,) = strategy_detect.candidates(conn, date(2026, 11, 14))
    assert found.scope == f"account:{viac.id}"
    assert (found.series.cadence, found.series.day, found.series.amount) == ("monthly", 25, 60_000)
    fin.detect_strategies()
    proposal_events.sync_events(ctx)
    (p,) = pending(ctx)
    assert p.preview["summary"] == "Versement régulier repéré : 600 CHF sur 3a VIAC chaque mois"
    assert p.preview["details"]["phrase"] == "Le 25 du mois, je verse 600 CHF sur 3a VIAC."
    accept(ctx, p)
    ((origin, scope),) = rows(fin, "SELECT origin, scope FROM strategies")
    assert (origin, scope) == ("detected", f"account:{viac.id}")
    events = rows(fin, "SELECT payload_json FROM events WHERE type = 'proposal.request'")
    assert all(
        json.loads(str(r[0]))["create_key"].startswith("finance:strategy-detect:") for r in events
    )


def test_only_a_buy_can_start_from_the_journal(
    ctx: HubContext, coins: FinanceDomain, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hub.core.errors import Problem
    from tests.finance.test_double_sas import create

    at(coins, monkeypatch, "2026-11-14")
    dca = {
        "kind": "recurring",
        "scope": "CRYPTO:BTC",
        "cadence": "monthly",
        "day": 1,
        "amount_minor": 20_000,
    }
    for bad in (
        dict(dca, since="2023-01-01"),  # plus de deux ans
        dict(dca, since="2026-12-01"),  # dans le futur
        {
            "kind": "dip",
            "scope": "CRYPTO:BTC",
            "drop_pct": 20,
            "window_days": 90,
            "amount_minor": 1_000,
            "since": "2026-06-01",
        },
        dict(dca, scope="account:inconnu"),
    ):
        with pytest.raises(Problem):
            create(ctx, "save_strategy", bad)
