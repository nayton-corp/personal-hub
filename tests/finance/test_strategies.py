"""Stratégies (migration 0027) : les règles pures des trois genres, la vérification de nuit
(une étape à la fois, une alerte par étape, constat au journal), les deux propositions et la
route. Le hub ne passe jamais d'ordre : rien ici n'écrit une opération."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from hub.core.context import HubContext
from hub.core.errors import Problem
from hub.domains.finance.domain import FinanceDomain
from hub.domains.finance.patrimoine.model import strategy as rules
from hub.domains.finance.patrimoine.model.strategy import Tier
from tests.finance.conftest import rows
from tests.finance.test_crypto_cost import doc
from tests.finance.test_double_sas import accept, client, create, ctx, fin
from tests.finance.test_exchange import op
from tests.finance.test_finance_api import token
from tests.finance.test_wealth import add_ref

__all__ = ["client", "ctx", "fin"]  # fixtures


# --- les règles, pures ---------------------------------------------------------------------


def test_tiers_are_few_and_far_apart() -> None:
    assert rules.tiers_problem([Tier(100, 25), Tier(150, 25)]) is None
    assert rules.tiers_problem([]) is not None
    assert (
        rules.tiers_problem([Tier(100, 25), Tier(105, 25)])
        == "au moins 10 points entre deux paliers"
    )
    assert rules.tiers_problem([Tier(100 + 10 * i, 10) for i in range(5)]) is not None


def test_ladder_opens_one_tier_at_a_time_in_order() -> None:
    tiers = [Tier(150, 50), Tier(100, 25)]
    assert rules.ladder_next(tiers, frozenset(), Decimal("99.9")) is None
    assert rules.ladder_next(tiers, frozenset(), None) is None  # sans prix d'achat
    # le niveau a sauté les deux paliers d'un coup : le premier d'abord
    assert rules.ladder_next(tiers, frozenset(), Decimal(180)) == Tier(100, 25)
    assert rules.ladder_next(tiers, frozenset({100}), Decimal(180)) == Tier(150, 50)
    assert rules.ladder_next(tiers, frozenset({100}), Decimal(120)) is None
    assert rules.ladder_next(tiers, frozenset({100, 150}), Decimal(300)) is None
    assert rules.planned_sale(210_000, 25) == 52_500
    assert rules.ratio_pct(0, 0) is None


def test_recurring_dates() -> None:
    d = date(2026, 11, 12)  # un jeudi
    assert rules.recurring_due("monthly", 5, d) == date(2026, 11, 5)
    assert rules.recurring_due("monthly", 20, d) == date(2026, 10, 20)
    assert rules.recurring_due("monthly", 20, date(2026, 1, 3)) == date(2025, 12, 20)
    assert rules.recurring_next("monthly", 5, d) == date(2026, 12, 5)
    assert rules.recurring_next("monthly", 28, date(2026, 12, 28)) == date(2027, 1, 28)
    assert rules.recurring_due("weekly", 0, d) == date(2026, 11, 9)
    assert rules.recurring_due("weekly", 3, d) == d
    assert rules.recurring_next("weekly", 3, d) == date(2026, 11, 19)
    assert rules.recurring_key("monthly", date(2026, 11, 5)) == "2026-11"
    assert rules.recurring_key("weekly", date(2026, 11, 9)) == "2026-11-09"


def test_dip_alerts_once_per_fall() -> None:
    today = date(2026, 11, 12)
    prices = [
        ("2026-06-01", Decimal(200)),
        ("2026-09-01", Decimal(100)),
        ("2026-11-10", Decimal(78)),
    ]
    d = rules.dip(prices, 90, today)  # le sommet de juin est hors de la fenêtre
    assert d is not None
    assert (d.peak_on, d.peak, d.last, d.drop_pct) == (
        "2026-09-01",
        Decimal(100),
        Decimal(78),
        Decimal(22),
    )
    assert rules.dip_reached(d, 20, None)
    assert not rules.dip_reached(d, 25, None)
    # déjà alerté après ce sommet : il faut un nouveau plus haut pour une nouvelle alerte
    assert not rules.dip_reached(d, 20, "2026-10-01")
    assert rules.dip_reached(d, 20, "2026-08-15")
    assert rules.dip([], 90, today) is None
    assert rules.settled(80, 100)
    assert not rules.settled(79, 100)
    assert not rules.settled(50, None)


# --- la vérification de nuit ---------------------------------------------------------------


def price(sym: str, on: str, value: str) -> dict[str, str]:
    return {
        "instrument": sym,
        "kind": "crypto",
        "on_date": on,
        "price": value,
        "currency": "CHF",
        "source": "coingecko",
    }


@pytest.fixture
def coins(fin: FinanceDomain) -> FinanceDomain:
    """Un compte crypto : 0.02 BTC payés 1 000, 1 ETH payé 2 000 (en mars)."""
    add_ref(fin, "crypto:binance", "crypto", "Binance")
    fin.importer.process(
        [
            doc(
                prices=[
                    price("BTC", "2026-03-01", "50000"),
                    price("ETH", "2026-03-01", "2000"),
                    price("BTC", "2026-10-01", "40000"),
                    price("ETH", "2026-10-01", "1800"),
                ],
                operations=[
                    op("fiat:1", "fiat_deposit", "2026-03-01", ("CHF", "3000", "deposit")),
                    op(
                        "b1",
                        "trade",
                        "2026-03-02",
                        ("CHF", "-1000", "trade"),
                        ("BTC", "0.02", "trade"),
                    ),
                    op(
                        "b2",
                        "trade",
                        "2026-03-02",
                        ("CHF", "-2000", "trade"),
                        ("ETH", "1", "trade"),
                    ),
                ],
            )
        ]
    )
    return fin


def at(fin: FinanceDomain, monkeypatch: pytest.MonkeyPatch, day: str) -> None:
    monkeypatch.setattr(fin, "today", lambda: date.fromisoformat(day))


def save(ctx: HubContext, params: dict[str, Any]) -> str:
    out = accept(ctx, create(ctx, "save_strategy", params))
    assert out.result is not None
    return str(out.result["strategy_id"])


def listed(client: TestClient, ctx: HubContext) -> dict[str, Any]:
    r = client.get("/api/finance/strategies", headers=token(ctx, "brain=finance"))
    assert r.status_code == 200, r.text
    return dict(r.json())


def notices(fin: FinanceDomain) -> list[tuple[str, str]]:
    import json

    found = rows(fin, "SELECT payload_json FROM events WHERE type = 'notify.request' ORDER BY seq")
    out = []
    for (raw,) in found:
        p = json.loads(raw)
        if p["click"].startswith("/#strategy="):
            out.append((p["title"], p["click"]))
    return out


ALT = {
    "kind": "ladder",
    "scope": "crypto:alt",
    "tiers": [{"at_pct": 100, "sell_pct": 25}, {"at_pct": 150, "sell_pct": 50}],
    "note": "replacer sur le fonds monde",
}


def test_ladder_from_alert_to_the_sale_seen_in_the_journal(
    client: TestClient, ctx: HubContext, coins: FinanceDomain, monkeypatch: pytest.MonkeyPatch
) -> None:
    at(coins, monkeypatch, "2026-10-05")
    p = create(ctx, "save_strategy", ALT)
    assert p.preview["summary"] == (
        "Nouvelle stratégie : Quand Altcoins revient à son prix d'achat, j'en vends 25 % ; "
        "à +50 %, 50 %."
    )
    accept(ctx, p)
    (s,) = listed(client, ctx)["items"]
    # les altcoins : l'ETH seul (le bitcoin n'en est pas), 1 800 pour 2 000 payés
    assert (s["state"], s["level"]["ratio_pct"], s["level"]["next_at_pct"]) == (
        "active",
        "90.0",
        100,
    )
    assert s["note"] == "replacer sur le fonds monde"
    assert coins.run_strategies() == []  # sous le prix d'achat : rien

    coins.importer.process([doc(prices=[price("ETH", "2026-10-20", "2100")])])
    at(coins, monkeypatch, "2026-10-20")
    (opened,) = coins.run_strategies()
    assert (opened.kind, opened.reminder) == ("ladder", False)
    assert coins.run_strategies() == []  # relancée le même jour : ni étape, ni alerte de plus
    # la notification passe par un service tiers : ni actif, ni montant
    assert notices(coins) == [("Stratégie : un palier est atteint", f"/#strategy={opened.step_id}")]
    (s,) = listed(client, ctx)["items"]
    step = s["step"]
    assert (s["state"], step["state"], step["key"]) == ("reached", "open", "t100")
    assert step["planned"]["minor"] == 52_500  # 25 % de 2 100
    assert [(r["key"], r["ratio_pct"]) for r in step["rows"]] == [("CRYPTO:ETH", "105.0")]

    # le cours passe le deuxième palier : une étape à la fois, rien de plus tant qu'elle attend
    coins.importer.process([doc(prices=[price("ETH", "2026-10-22", "3200")])])
    at(coins, monkeypatch, "2026-10-22")
    assert coins.run_strategies() == []

    # il vend lui-même ; le hub le voit au journal et coche l'étape, puis ouvre la suivante
    sale = op("s1", "trade", "2026-10-23", ("ETH", "-0.2", "trade"), ("CHF", "640", "trade"))
    coins.importer.process([doc(operations=[sale])])
    at(coins, monkeypatch, "2026-10-23")
    (second,) = coins.run_strategies()
    (s,) = listed(client, ctx)["items"]
    assert s["step"]["key"] == "t150"
    assert s["step"]["id"] == second.step_id
    done = s["steps"][-1]
    assert (done["key"], done["state"], done["closed_by"]) == ("t100", "done", "journal")
    assert done["done"]["minor"] == 64_000
    assert s["kept"] == {"done": 1, "skipped": 0}
    assert len(notices(coins)) == 2


def test_answers_later_skip_done(
    client: TestClient, ctx: HubContext, coins: FinanceDomain, monkeypatch: pytest.MonkeyPatch
) -> None:
    at(coins, monkeypatch, "2026-10-05")
    one = dict(
        ALT,
        scope="CRYPTO:ETH",
        tiers=[{"at_pct": 90, "sell_pct": 10}, {"at_pct": 100, "sell_pct": 50}],
    )
    strategy_id = save(ctx, one)
    (opened,) = coins.run_strategies()  # 90 % : le premier palier est déjà atteint
    later = create(ctx, "answer_strategy_step", {"step_id": opened.step_id, "answer": "later"})
    assert later.preview["summary"].startswith("Étape de stratégie, plus tard : Quand Ethereum")
    accept(ctx, later)
    (s,) = listed(client, ctx)["items"]
    assert (s["state"], s["step"]["state"]) == ("reached", "later")
    assert coins.run_strategies() == []  # « plus tard » : elle attend, sans autre alerte
    with pytest.raises(Problem):
        create(ctx, "answer_strategy_step", {"step_id": opened.step_id, "answer": "later"})
    accept(ctx, create(ctx, "answer_strategy_step", {"step_id": opened.step_id, "answer": "skip"}))
    (s,) = listed(client, ctx)["items"]
    assert (s["step"], s["kept"]) == (None, {"done": 0, "skipped": 1})
    assert s["steps"][0]["closed_by"] == "user"
    with pytest.raises(Problem):  # close : plus de réponse
        create(ctx, "answer_strategy_step", {"step_id": opened.step_id, "answer": "done"})
    assert coins.run_strategies() == []  # un palier passé ne revient pas

    # en pause : plus rien n'est vérifié ; terminée : ce qui attendait est clos
    coins.importer.process([doc(prices=[price("ETH", "2026-10-20", "2100")])])
    at(coins, monkeypatch, "2026-10-20")
    accept(ctx, create(ctx, "save_strategy", {"strategy_id": strategy_id, "status": "paused"}))
    assert coins.run_strategies() == []
    accept(ctx, create(ctx, "save_strategy", {"strategy_id": strategy_id, "status": "active"}))
    (second,) = coins.run_strategies()
    accept(ctx, create(ctx, "answer_strategy_step", {"step_id": second.step_id, "answer": "done"}))
    (s,) = listed(client, ctx)["items"]
    assert (s["state"], s["kept"]) == ("complete", {"done": 1, "skipped": 1})
    accept(ctx, create(ctx, "save_strategy", {"strategy_id": strategy_id, "status": "ended"}))
    (s,) = listed(client, ctx)["items"]
    assert s["state"] == "ended"
    with pytest.raises(Problem):
        create(ctx, "save_strategy", {"strategy_id": strategy_id, "status": "active"})


def test_recurring_reminds_once_and_ticks_from_the_journal(
    client: TestClient, ctx: HubContext, coins: FinanceDomain, monkeypatch: pytest.MonkeyPatch
) -> None:
    at(coins, monkeypatch, "2026-10-10")
    dca = {
        "kind": "recurring",
        "scope": "CRYPTO:BTC",
        "cadence": "monthly",
        "day": 5,
        "amount_minor": 20_000,
    }
    p = create(ctx, "save_strategy", dca)
    assert p.preview["summary"] == (
        "Nouvelle stratégie : Le 5 du mois, j'achète pour 200 CHF de Bitcoin."
    )
    accept(ctx, p)
    assert coins.run_strategies() == []  # l'échéance du 5 est d'avant la stratégie : rien de dû
    (s,) = listed(client, ctx)["items"]
    assert s["level"] == {"next_on": "2026-11-05"}

    at(coins, monkeypatch, "2026-11-05")
    (opened,) = coins.run_strategies()
    assert notices(coins)[-1][0] == "Stratégie : c'est le jour d'un achat prévu"
    at(coins, monkeypatch, "2026-11-07")
    assert coins.run_strategies() == []
    at(coins, monkeypatch, "2026-11-08")  # trois jours après : un seul rappel
    (again,) = coins.run_strategies()
    assert (again.step_id, again.reminder) == (opened.step_id, True)
    at(coins, monkeypatch, "2026-11-09")
    assert coins.run_strategies() == []
    assert [t for t, _ in notices(coins)][
        -1
    ] == "Stratégie : un achat prévu n'est pas encore au journal"

    # l'achat arrive au journal : l'étape se coche seule
    buy = op("b3", "trade", "2026-11-09", ("CHF", "-200", "trade"), ("BTC", "0.005", "trade"))
    coins.importer.process(
        [doc(operations=[op("f2", "fiat_deposit", "2026-11-09", ("CHF", "400", "deposit")), buy])]
    )
    at(coins, monkeypatch, "2026-11-10")
    assert coins.run_strategies() == []
    (s,) = listed(client, ctx)["items"]
    assert (s["state"], s["steps"][0]["state"], s["steps"][0]["closed_by"]) == (
        "active",
        "done",
        "journal",
    )

    # le mois suivant, acheté deux jours avant l'échéance : coché sans alerte
    early = op("b4", "trade", "2026-12-03", ("CHF", "-200", "trade"), ("BTC", "0.005", "trade"))
    coins.importer.process([doc(operations=[early])])
    at(coins, monkeypatch, "2026-12-05")
    before = len(notices(coins))
    assert coins.run_strategies() == []
    (s,) = listed(client, ctx)["items"]
    assert [(x["key"], x["state"]) for x in s["steps"]] == [
        ("2026-12", "done"),
        ("2026-11", "done"),
    ]
    assert len(notices(coins)) == before

    # un mois sans achat ni réponse : l'étape passe quand l'échéance suivante arrive
    at(coins, monkeypatch, "2027-01-05")
    coins.run_strategies()
    at(coins, monkeypatch, "2027-02-05")
    coins.run_strategies()
    (s,) = listed(client, ctx)["items"]
    assert [(x["key"], x["state"], x["closed_by"]) for x in s["steps"][:2]] == [
        ("2027-02", "open", None),
        ("2027-01", "skipped", "expired"),
    ]


def test_dip_needs_a_big_fall_and_a_fresh_price(
    client: TestClient, ctx: HubContext, coins: FinanceDomain, monkeypatch: pytest.MonkeyPatch
) -> None:
    at(coins, monkeypatch, "2026-10-05")
    dip = {
        "kind": "dip",
        "scope": "CRYPTO:BTC",
        "drop_pct": 20,
        "window_days": 90,
        "amount_minor": 50_000,
    }
    p = create(ctx, "save_strategy", dip)
    assert p.preview["summary"] == (
        "Nouvelle stratégie : Si Bitcoin baisse de 20 % depuis son plus haut des 3 derniers "
        "mois, j'en achète pour 500 CHF."
    )
    accept(ctx, p)
    assert coins.run_strategies() == []  # un seul cours dans la fenêtre : pas de baisse
    coins.importer.process([doc(prices=[price("BTC", "2026-10-20", "33000")])])
    at(coins, monkeypatch, "2026-10-20")
    assert coins.run_strategies() == []  # −17,5 % : pas assez
    coins.importer.process([doc(prices=[price("BTC", "2026-10-22", "31000")])])
    at(coins, monkeypatch, "2026-11-05")
    assert coins.run_strategies() == []  # −22,5 %, mais le dernier cours a deux semaines
    at(coins, monkeypatch, "2026-10-22")
    (opened,) = coins.run_strategies()
    assert opened.kind == "dip"
    (s,) = listed(client, ctx)["items"]
    assert s["step"]["detail"] == {"drop_pct": "22.5", "peak_on": "2026-10-01"}
    assert s["step"]["planned"]["minor"] == 50_000
    accept(ctx, create(ctx, "answer_strategy_step", {"step_id": opened.step_id, "answer": "skip"}))
    coins.importer.process([doc(prices=[price("BTC", "2026-10-24", "28000")])])
    at(coins, monkeypatch, "2026-10-24")
    assert coins.run_strategies() == []  # la même baisse qui continue : pas de deuxième alerte


def test_refusals_and_scopes(
    client: TestClient, ctx: HubContext, coins: FinanceDomain, monkeypatch: pytest.MonkeyPatch
) -> None:
    at(coins, monkeypatch, "2026-10-05")
    scopes = listed(client, ctx)["scopes"]
    assert [(x["key"], x["kind"], x["value"]["minor"]) for x in scopes] == [
        ("crypto:alt", "group", 180_000),
        ("crypto:all", "group", 260_000),
        ("CRYPTO:ETH", "crypto", 180_000),
        ("CRYPTO:BTC", "crypto", 80_000),
    ]
    bad = [
        {"kind": "ladder", "scope": "CRYPTO:NOPE", "tiers": ALT["tiers"]},  # cible inconnue
        {"kind": "ladder", "scope": "crypto:alt"},  # sans palier
        dict(ALT, tiers=[{"at_pct": 100, "sell_pct": 25}, {"at_pct": 105, "sell_pct": 25}]),
        dict(ALT, amount_minor=10_000),  # réglage d'un autre genre
        {
            "kind": "recurring",
            "scope": "crypto:alt",
            "cadence": "monthly",
            "day": 5,
            "amount_minor": 10_000,
        },
        {
            "kind": "recurring",
            "scope": "CRYPTO:BTC",
            "cadence": "monthly",
            "day": 0,
            "amount_minor": 10_000,
        },
        {
            "kind": "recurring",
            "scope": "CRYPTO:BTC",
            "cadence": "weekly",
            "day": 7,
            "amount_minor": 10_000,
        },
    ]
    for params in bad:
        with pytest.raises(Problem):
            create(ctx, "save_strategy", params)
    with pytest.raises(Problem):  # une petite baisse n'est pas une stratégie
        create(
            ctx,
            "save_strategy",
            {
                "kind": "dip",
                "scope": "CRYPTO:BTC",
                "drop_pct": 5,
                "window_days": 90,
                "amount_minor": 10_000,
            },
        )
    strategy_id = save(ctx, ALT)
    with pytest.raises(Problem):
        create(ctx, "save_strategy", {"strategy_id": strategy_id, "scope": "crypto:all"})
    with pytest.raises(Problem):  # aucun changement
        create(ctx, "save_strategy", {"strategy_id": strategy_id, "note": ALT["note"]})
    accept(ctx, create(ctx, "save_strategy", {"strategy_id": strategy_id, "note": ""}))
    accept(
        ctx,
        create(
            ctx,
            "save_strategy",
            {"strategy_id": strategy_id, "tiers": [{"at_pct": 120, "sell_pct": 30}]},
        ),
    )
    (s,) = listed(client, ctx)["items"]
    assert (s["note"], s["phrase"]) == (
        None,
        "Quand Altcoins dépasse son prix d'achat de 20 %, j'en vends 30 %.",
    )
    assert rows(coins, "SELECT count(*) FROM entries WHERE booking_date > '2026-10-01'") == [(0,)]


def test_tables_survive_a_rebuild(coins: FinanceDomain) -> None:
    from hub.domains.finance import rebuild

    assert {"save_strategy", "answer_strategy_step"} <= rebuild.REFERENCE_KINDS
    with coins.engine().connect() as conn:
        tables = set(
            conn.execute(text("SELECT name FROM sqlite_master WHERE type = 'table'")).scalars()
        )
    assert {"strategies", "strategy_steps"} <= tables
