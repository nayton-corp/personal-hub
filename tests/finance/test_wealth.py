"""Lot 6 : cours et soldes crypto, positions saisies à la main, transparence des fonds,
virements appariés, abonnements, et leurs routes."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, text

from hub.api.app import create_app
from hub.core import tokens
from hub.core.context import HubContext
from hub.core.db import begin_immediate
from hub.core.registry import Registry
from hub.domains.finance import (
    catalog,
    insights,
    ledger,
    lookthrough,
    manual,
    market,
    recurring,
    rules,
    transfers,
    valuation,
)
from hub.domains.finance.domain import FinanceDomain
from hub.domains.finance.importer import Incoming
from tests.factories.camt import IBAN, Stmt, Tx, camt053
from tests.finance.conftest import (
    add_account,
    finance_settings,
    open_account,
    ready_account,
    rows,
    without_seed_rules,
)

WORLD = "IE00B3RBWM25"  # ISIN fictif pour le test (forme valide)
SPI = "CH0237935652"


def market_doc(**kw: object) -> bytes:
    return json.dumps(
        {"format": market.FORMAT, "fetched_at": "2026-10-27T07:00:00Z", **kw}
    ).encode()


def add_ref(
    finance: FinanceDomain, ref: str, kind: str, name: str = "Compte", currency: str = "CHF"
) -> catalog.Account:
    with begin_immediate(finance.engine()) as conn:
        return catalog.add_account(
            conn, institution="Test", name=name, kind=kind, external_ref=ref, currency=currency
        )


# --- cours du marché et portefeuilles crypto ---------------------------------------------------


def test_market_file_fx_prices_and_wallet(finance: FinanceDomain) -> None:
    doc = market_doc(
        fx=[
            {"on_date": "2026-10-26", "base": "EUR", "quote": "CHF", "rate": 0.93, "source": "ecb"}
        ],
        prices=[
            {
                "instrument": "BTC",
                "kind": "crypto",
                "on_date": "2026-10-26",
                "price": 90000.5,
                "currency": "CHF",
                "source": "coingecko",
            }
        ],
        balances=[
            {
                "account": "crypto:ledger-btc",
                "instrument": "BTC",
                "on_date": "2026-10-26",
                "quantity": "0.5",
            }
        ],
    )
    assert market.is_market(doc)
    report = finance.importer.process([Incoming("market.json", doc)])
    assert {(s.index, s.status, tuple(s.reasons)) for s in report.statements} == {
        (0, "applied", ()),
        (1, "needs_review", ("unknown_account",)),
    }
    assert rows(finance, "SELECT base, rate, source FROM fx_rates") == [("EUR", "0.93", "ecb")]
    assert rows(finance, "SELECT isin, price, currency FROM prices") == [
        ("CRYPTO:BTC", "90000.5", "CHF")
    ]
    wallet = add_ref(finance, "crypto:ledger-btc", "crypto", "Ledger")
    retried = finance.importer.retry_needs_review()
    assert [o.status for o in retried] == ["applied"]
    assert rows(finance, "SELECT isin, quantity, value_minor FROM holdings") == [
        ("CRYPTO:BTC", "0.5", 4_500_025)
    ]
    assert rows(finance, "SELECT name, kind FROM instruments") == [("Bitcoin", "crypto")]
    # le jour suivant, un nouveau cours fait bouger la valeur sans nouveau relevé
    finance.importer.process(
        [
            Incoming(
                "m2.json",
                market_doc(
                    prices=[
                        {
                            "instrument": "BTC",
                            "kind": "crypto",
                            "on_date": "2026-10-27",
                            "price": "100000",
                            "currency": "CHF",
                            "source": "coingecko",
                        }
                    ]
                ),
            )
        ]
    )
    with finance.engine().connect() as conn:
        v = valuation.value_at(conn, "2026-10-27")
    assert v.by_envelope["crypto"] == 5_000_000
    assert v.deposits == 0
    with finance.engine().connect() as conn:
        assert valuation.account_value(valuation.Positions(conn), wallet.id, 0, "2026-10-25") == (
            0,
            [],
        )


def test_platform_balances_value_each_crypto_and_wait_for_missing_prices(
    finance: FinanceDomain,
) -> None:
    add_ref(finance, "crypto:binance", "crypto", "Binance")
    price = {"kind": "crypto", "on_date": "2026-10-27", "currency": "CHF", "source": "coingecko"}
    finance.importer.process(
        [Incoming("m.json", market_doc(prices=[{**price, "instrument": "ETH", "price": "3000"}]))]
    )
    held = [("ETH", "1.5"), ("PEPE", "1000000")]
    doc = market_doc(
        balances=[
            {"account": "crypto:binance", "instrument": i, "on_date": "2026-10-27", "quantity": q}
            for i, q in held
        ]
    )
    report = finance.importer.process([Incoming("binance.json", doc)])
    assert {(s.index, s.status) for s in report.statements} == {
        (0, "applied"),
        (1, "applied"),
        (2, "applied"),
    }
    assert rows(finance, "SELECT isin, quantity, value_minor FROM holdings ORDER BY isin") == [
        ("CRYPTO:ETH", "1.5", 450_000),
        ("CRYPTO:PEPE", "1000000", 0),
    ]
    with finance.engine().connect() as conn:
        assert valuation.value_at(conn, "2026-10-27").by_envelope["crypto"] == 450_000


def test_wallet_history_is_valued_with_old_usd_prices(finance: FinanceDomain) -> None:
    add_ref(finance, "crypto:ledger", "crypto", "Ledger")
    doc = market_doc(
        fx=[
            {"on_date": "2024-03-01", "base": "USD", "quote": "CHF", "rate": "0.9", "source": "ecb"}
        ],
        prices=[
            {
                "instrument": "BTC",
                "kind": "crypto",
                "on_date": "2024-03-01",
                "price": "60000.5",
                "currency": "USD",
                "source": "binance",
            }
        ],
        balances=[
            {"account": "crypto:ledger", "instrument": "BTC", "on_date": d, "quantity": q}
            for d, q in [("2024-03-01", "1"), ("2024-06-01", "0.5")]
        ],
    )
    finance.importer.process([Incoming("market.json", doc)])
    with finance.engine().connect() as conn:
        assert valuation.value_at(conn, "2024-04-15").by_envelope["crypto"] == 5_400_045
        assert (
            valuation.value_at(conn, "2024-06-15").by_envelope["crypto"] == 2_700_022
        )  # 27 000.225 arrondi au pair
        assert valuation.value_at(conn, "2024-02-15").by_envelope.get("crypto", 0) == 0


def test_market_file_refusals() -> None:
    with pytest.raises(market.MarketError):
        market.parse(
            market_doc(
                fx=[{"on_date": "x", "base": "EUR", "quote": "CHF", "rate": 1, "source": "ecb"}]
            )
        )
    with pytest.raises(market.MarketError):
        market.parse(
            market_doc(
                balances=[
                    {
                        "account": "bcf",
                        "instrument": "BTC",
                        "on_date": "2026-10-27",
                        "quantity": "1",
                    }
                ]
            )
        )
    with pytest.raises(market.MarketError):
        market.parse(b'{"format": "autre"}')
    assert not market.is_market(b"[1, 2]")


def test_foreign_cash_account_uses_fx(finance: FinanceDomain) -> None:
    eur = add_ref(finance, "revolut:EUR", "cash", "Revolut EUR", "EUR")
    open_account(finance, eur, "2026-10-01", 10_000)
    with finance.engine().connect() as conn:
        assert valuation.value_at(conn, "2026-10-27").missing_fx == [eur.id]
    finance.importer.process(
        [
            Incoming(
                "fx.json",
                market_doc(
                    fx=[
                        {
                            "on_date": "2026-10-01",
                            "base": "EUR",
                            "quote": "CHF",
                            "rate": "0.9",
                            "source": "ecb",
                        }
                    ]
                ),
            )
        ]
    )
    with finance.engine().connect() as conn:
        v = valuation.value_at(conn, "2026-10-27")
    assert (v.net_worth, v.deposits, v.missing_fx) == (9_000, 9_000, [])


# --- positions saisies à la main ---------------------------------------------------------------

POSITIONS = (
    "date,account,instrument,name,kind,quantity,price,currency\n"
    f"2026-10-20,revolut:invest,{WORLD},Fonds Monde,etf,10,100,USD\n"
    "2026-10-20,revolut:invest,AAPL,Apple,stock,2,200,USD\n"
    "2026-10-20,revolut:crypto,ETH,,crypto,1.5,3000,CHF\n"
)


def test_manual_positions(finance: FinanceDomain) -> None:
    data = POSITIONS.encode()
    assert manual.is_positions(data)
    doc = manual.parse(data)
    assert [(s.account, len(s.rows)) for s in doc.snapshots] == [
        ("revolut:crypto", 1),
        ("revolut:invest", 2),
    ]
    add_ref(finance, "revolut:invest", "securities", "Revolut actions")
    add_ref(finance, "revolut:crypto", "crypto", "Revolut crypto")
    finance.importer.process(
        [
            Incoming(
                "fx.json",
                market_doc(
                    fx=[
                        {
                            "on_date": "2026-10-20",
                            "base": "USD",
                            "quote": "CHF",
                            "rate": "0.8",
                            "source": "ecb",
                        }
                    ]
                ),
            )
        ]
    )
    report = finance.importer.process([Incoming("positions.csv", data)])
    assert {s.status for s in report.statements} == {"applied"}
    keys = {r[0] for r in rows(finance, "SELECT isin FROM holdings")}
    assert keys == {WORLD, "SYM:AAPL", "CRYPTO:ETH"}
    with finance.engine().connect() as conn:
        v = valuation.value_at(conn, "2026-10-27")
    assert v.by_envelope["titres"] == (1000 + 400) * 80
    assert v.by_envelope["crypto"] == 450_000
    with finance.engine().connect() as conn:
        h = insights.holdings(conn, "2026-10-27")
    assert {i["isin"]: i["price_currency"] for i in h["items"]}["SYM:AAPL"] == "USD"


def test_manual_positions_refusals() -> None:
    bad = POSITIONS.replace("2026-10-20,revolut:invest,AAPL", "20.10.2026,revolut:invest,AAPL")
    with pytest.raises(manual.PositionsError, match="date"):
        manual.parse(bad.encode())
    with pytest.raises(manual.PositionsError, match="type"):
        manual.parse(POSITIONS.replace(",stock,", ",option,").encode())
    with pytest.raises(manual.PositionsError, match="devise"):
        manual.parse(POSITIONS.replace(",CHF\n", ",XBT\n").encode())


def test_deposits_ignore_off_ledger_purchases(finance: FinanceDomain) -> None:
    """Un paiement qui achète des cryptos gardées hors registre ne sort pas du patrimoine."""
    without_seed_rules(finance)
    a = add_account(finance)
    open_account(finance, a, "2026-09-30", 500_000)
    with begin_immediate(finance.engine()) as conn:
        seq = _entry(conn, a, "2026-10-05", -100_000, counterparty="Bourse crypto")
        rules.categorize(
            conn,
            seq,
            rules.Rule("system-viac-trade", "search_text", "x", "any", "transfer-titres", 1, True),
            proposal_id=None,
            created_at="2026-10-05T00:00:00.000Z",
        )
    with finance.engine().connect() as conn:
        v = valuation.value_at(conn, "2026-10-27")
    assert (v.net_worth, v.deposits) == (400_000, 500_000)


def test_crypto_performance_from_bank_payments_and_arrivals(finance: FinanceDomain) -> None:
    """Investi = virements de la catégorie « Crypto » ; coût par actif = valeur à l'arrivée."""
    without_seed_rules(finance)
    bank = add_account(finance)
    open_account(finance, bank, "2026-09-30", 500_000)
    crypto_rule = rules.Rule("system-viac-trade", "search_text", "x", "any", "crypto", 14, True)
    with begin_immediate(finance.engine()) as conn:
        for on, amount in [("2026-10-01", -100_000), ("2026-10-10", -50_000)]:
            seq = _entry(conn, bank, on, amount, counterparty="SwissBorg")
            rules.categorize(conn, seq, crypto_rule, proposal_id=None, created_at=f"{on}T00:00Z")
    add_ref(finance, "crypto:ledger", "crypto", "Ledger")
    price = {"kind": "crypto", "currency": "CHF", "source": "coingecko", "instrument": "BTC"}
    doc = market_doc(
        prices=[
            {**price, "on_date": d, "price": p}
            for d, p in [("2026-10-02", "50000"), ("2026-10-11", "60000"), ("2026-10-27", "70000")]
        ],
        balances=[
            {"account": "crypto:ledger", "instrument": "BTC", "on_date": d, "quantity": q}
            for d, q in [("2026-10-02", "0.019"), ("2026-10-11", "0.027"), ("2026-10-27", "0.027")]
        ],
    )
    finance.importer.process([Incoming("market.json", doc)])
    with finance.engine().connect() as conn:
        v = valuation.value_at(conn, "2026-10-27")
        h = insights.holdings(conn, "2026-10-27")
    # le virement achète des cryptos : il ne sort pas du patrimoine
    assert (v.net_worth, v.deposits) == (350_000 + 189_000, 500_000)
    (line,) = h["items"]
    # 0.019 arrivés à 50 000, puis 0.008 à 60 000
    assert (line["cost"]["minor"], line["gain"]["minor"]) == (143_000, 46_000)
    c = h["crypto"]
    assert (c["invested"]["minor"], c["value"]["minor"], c["result"]["minor"]) == (
        150_000,
        189_000,
        39_000,
    )
    assert c["missing_prices"] is False


def test_arrival_cost_follows_sales_and_missing_prices(finance: FinanceDomain) -> None:
    add_ref(finance, "crypto:phantom", "crypto", "Phantom")
    sol = {"kind": "crypto", "currency": "CHF", "source": "coingecko", "instrument": "SOL"}
    doc = market_doc(
        prices=[{**sol, "on_date": "2026-10-01", "price": "100"}],
        balances=[
            {"account": "crypto:phantom", "instrument": i, "on_date": d, "quantity": q}
            for i, d, q in [
                ("SOL", "2026-10-01", "4"),
                ("SOL", "2026-10-05", "1"),  # trois quarts vendus : un quart du coût reste
                ("SOL", "2026-10-06", "1"),
                ("ABC", "2026-10-06", "5"),  # sans cours : pas de coût
            ]
        ],
    )
    finance.importer.process([Incoming("market.json", doc)])
    with finance.engine().connect() as conn:
        h = insights.holdings(conn, "2026-10-06")
    costs = {i["isin"]: i["cost"] and i["cost"]["minor"] for i in h["items"]}
    assert costs == {"CRYPTO:SOL": 10_000, "CRYPTO:ABC": None}
    assert h["crypto"]["invested"]["minor"] == 0
    assert h["crypto"]["missing_prices"] is True


# --- transparence -------------------------------------------------------------------------------

ISHARES = (
    "iShares Core MSCI World UCITS ETF\n"
    'Fund Holdings as of,"Oct 24, 2026"\n'
    "\n"
    "Ticker,Name,Sector,Asset Class,Market Value,Weight (%),Notional Value,Quantity,Price,"
    "Location,Exchange,Currency,FX Rate,Market Currency\n"
    'AAPL,APPLE INC,Information Technology,Equity,"1,000.00",5.00,1,1,1,United States,'
    "NASDAQ,USD,1,USD\n"
    "NESN,NESTLE SA,Consumer Staples,Equity,100,1.00,1,1,1,Switzerland,SIX,CHF,1,CHF\n"
    "TM,TOYOTA,Consumer Discretionary,Equity,100,4.00,1,1,1,Japan,Tokyo,JPY,1,JPY\n"
    "USD,USD CASH,Cash and/or Derivatives,Cash,10,0.00,1,1,1,United States,-,USD,1,USD\n"
)


def test_issuer_holdings_list(finance: FinanceDomain) -> None:
    data = ISHARES.encode()
    source = lookthrough.detect(f"{WORLD}_holdings.csv", data)
    assert source == f"lookthrough:{WORLD}"
    assert lookthrough.detect("holdings.csv", data) is None  # sans ISIN dans le nom
    (comp,) = lookthrough.parse(source, data).compositions
    assert comp.on_date == "2026-10-24"
    region = {w.bucket: w.weight for w in comp.weights if w.dimension == "region"}
    assert region == {
        lookthrough.NORTH_AMERICA: Decimal("0.5"),
        lookthrough.SWITZERLAND: Decimal("0.1"),
        lookthrough.JAPAN: Decimal("0.4"),
    }
    sector = {w.bucket for w in comp.weights if w.dimension == "sector"}
    assert "Technologie" in sector
    report = finance.importer.process([Incoming(f"{WORLD}_holdings.csv", data)])
    assert report.counters()["applied"] == 1
    assert rows(finance, "SELECT count(DISTINCT dimension) FROM compositions") == [(4,)]


def test_generic_composition_and_breakdown(finance: FinanceDomain) -> None:
    generic = (
        "isin,dimension,bucket,weight_pct,on_date\n"
        f"{WORLD},region,Amérique du Nord,70,2026-09-30\n"
        f"{WORLD},region,Europe (hors Suisse),20,2026-09-30\n"
    ).encode()
    assert lookthrough.detect("fiche.csv", generic) == lookthrough.SOURCE
    add_ref(finance, "revolut:invest", "securities")
    add_ref(finance, "revolut:crypto", "crypto")
    finance.importer.process(
        [
            Incoming(
                "fx.json",
                market_doc(
                    fx=[
                        {
                            "on_date": "2026-10-20",
                            "base": "USD",
                            "quote": "CHF",
                            "rate": "1",
                            "source": "ecb",
                        }
                    ]
                ),
            ),
            Incoming("positions.csv", POSITIONS.encode()),
            Incoming("fiche.csv", generic),
        ]
    )
    with finance.engine().connect() as conn:
        out = lookthrough.breakdown(conn, "region", "2026-10-27")
        cur = lookthrough.breakdown(conn, "currency", "2026-10-27")
        top = lookthrough.breakdown(conn, "holding", "2026-10-27")
    items = {i["bucket"]: i["value"]["minor"] for i in out["items"]}
    # fonds : 1000 → 700 / 200 / 100 non ventilé ; Apple 400 non ventilé ; ETH 4500 crypto
    assert items == {
        lookthrough.NORTH_AMERICA: 70_000,
        lookthrough.EUROPE: 20_000,
        lookthrough.CRYPTO: 450_000,
        lookthrough.UNKNOWN: 50_000,
    }
    assert out["items"][-1]["bucket"] == lookthrough.UNKNOWN  # le reste en dernier
    assert out["covered"] == "0.1695"
    assert {i["bucket"] for i in cur["items"]} == {"USD", "CHF"}
    assert top["items"][0]["bucket"] == "Ethereum"
    # une composition plus ancienne ne remplace pas la plus récente
    older = generic.replace(b"2026-09-30", b"2026-01-31").replace(b",70,", b",60,")
    finance.importer.process([Incoming("vieille.csv", older)])
    assert rows(finance, "SELECT max(on_date) FROM compositions") == [("2026-09-30",)]


# --- virements appariés et abonnements ---------------------------------------------------------


def _entry(
    conn: Connection,
    account: catalog.Account,
    on: str,
    amount: int,
    *,
    counterparty: str | None = None,
    iban: str | None = None,
    code: str | None = None,
    label: str = "",
) -> int:
    seq, _ = ledger.append_entry(
        conn,
        ledger.NewEntry(
            account_id=account.id,
            booking_date=on,
            amount_minor=amount,
            currency=account.currency,
            counterparty=counterparty,
            counterparty_iban=iban,
            bank_tx_code=code,
            label=label,
            dedup_key=ledger.dedup_hash(f"test|{account.id}|{on}|{amount}|{counterparty}|{label}"),
        ),
    )
    return seq


REVOLUT_IBAN = "LT601010012345678901"


def test_transfers_are_matched(finance: FinanceDomain) -> None:
    without_seed_rules(finance)
    bcf = add_account(finance)
    rev = add_ref(finance, "revolut:CHF", "cash", "Revolut")
    savings = add_account(finance, iban="CH5604835012345678009")
    with begin_immediate(finance.engine()) as conn:
        # BCF → épargne : IBAN de contrepartie connu des deux côtés
        a = _entry(conn, bcf, "2026-10-02", -50_000, iban="CH5604835012345678009")
        b = _entry(conn, savings, "2026-10-03", 50_000, iban=IBAN)
        # BCF → Revolut : IBAN de Revolut inconnu, recharge sans contrepartie
        c = _entry(conn, bcf, "2026-10-10", -20_000, iban=REVOLUT_IBAN, counterparty="Revolut")
        d = _entry(conn, rev, "2026-10-11", 20_000, label="Top-up")
        # deux paiements identiques : aucun ne s'apparie au hasard
        _entry(conn, bcf, "2026-10-20", -3_000, counterparty="Boulangerie")
        _entry(conn, rev, "2026-10-20", 3_000, label="Remboursement")
        _entry(conn, rev, "2026-10-21", -3_000, label="Café")
    # la recharge BCF n'est pas encore un virement : la catégoriser par une règle
    with begin_immediate(finance.engine()) as conn:
        rules.categorize(
            conn,
            c,
            rules.Rule("system-transfer-own", "search_text", "revolut", "any", "transfer-own", 1),
            proposal_id=None,
            created_at="2026-10-10T00:00:00.000Z",
        )
    finance.refresh_derived()
    links = rows(finance, "SELECT debit_seq, credit_seq, method FROM transfer_links ORDER BY 1")
    assert links == [(a, b, "iban"), (c, d, "amount")]
    with finance.engine().connect() as conn:
        assert transfers.peer(conn, d)["account"] == "Compte privé"  # type: ignore[index]
        # la recharge Revolut, sans catégorie, compte comme un virement dans le budget
        cat = conn.execute(
            text("SELECT category_id FROM v_entry_allocation WHERE entry_seq = :s"), {"s": d}
        ).scalar_one()
        assert cat == "transfer-own"
        s = transfers.summary(conn, detailed=True)
    assert s["pairs"] == 2
    assert s["by_method"] == {"amount": 1, "iban": 1}


def test_pocket_transfer_beats_catch_all_rule(finance: FinanceDomain) -> None:
    """Compte Revolut → poche : ni IBAN ni code de virement, mais le même établissement, le même
    montant et le même jour. La règle « tout crédit restant → Autres revenus » ne doit pas en
    faire un revenu ; une catégorie précise, elle, reste la sienne."""
    without_seed_rules(finance)
    rev = add_ref(finance, "revolut:CHF", "cash", "Revolut")
    pocket = add_ref(finance, "revolut:CHF:poche-1", "cash", "Revolut")
    bcf = add_account(finance)
    with begin_immediate(finance.engine()) as conn:
        out = _entry(conn, rev, "2026-10-05", -40_000, label="To pocket CHF Vacances")
        into = _entry(conn, pocket, "2026-10-05", 40_000, label="From CHF")
        # même montant, même jour, mais deux établissements sans indice de virement
        _entry(conn, bcf, "2026-10-08", -1_500, counterparty="Kiosque")
        gift = _entry(conn, pocket, "2026-10-08", 1_500, label="Cadeau")
        # à deux jours d'écart, une poche n'est pas appariée sur le seul établissement
        _entry(conn, rev, "2026-10-12", -2_500, label="Achat")
        _entry(conn, pocket, "2026-10-14", 2_500, label="Retour")
        catch_all = rules.Rule("pack-base-x", "search_text", "", "credit", "autres-revenus", 29)
        precise = rules.Rule("user-x", "search_text", "from chf", "credit", "remboursements", 10)
        for r in (catch_all, precise):
            conn.execute(
                text(
                    "INSERT INTO rules (id, field, pattern, direction, category_id, priority, "
                    "created_at) VALUES (:i, :f, :p, :d, :c, :n, '2026-10-01T00:00:00.000Z')"
                ),
                {
                    "i": r.id,
                    "f": r.field,
                    "p": r.pattern,
                    "d": r.direction,
                    "c": r.category_id,
                    "n": r.priority,
                },
            )
        for seq in (into, gift):
            rules.categorize(
                conn, seq, catch_all, proposal_id=None, created_at="2026-10-05T00:00:00.000Z"
            )
    finance.refresh_derived()
    assert rows(finance, "SELECT debit_seq, credit_seq, method FROM transfer_links") == [
        (out, into, "amount")
    ]

    def shown(seq: int) -> tuple[str | None, str | None]:
        with finance.engine().connect() as conn:
            r = conn.execute(
                text(
                    "SELECT vs.category_id, va.category_id FROM v_entry_shown vs "
                    "JOIN v_entry_allocation va USING (entry_seq) WHERE vs.entry_seq = :s"
                ),
                {"s": seq},
            ).one()
            return r[0], r[1]

    assert shown(out) == ("transfer-own", "transfer-own")  # plus « à classer »
    assert shown(into) == ("transfer-own", "transfer-own")  # plus un revenu
    assert shown(gift) == ("autres-revenus", "autres-revenus")  # pas apparié
    with finance.engine().connect() as conn:
        assert insights.to_categorize(conn) == 3  # le kiosque, l'achat et le retour
    # une catégorie précise passe avant l'appariement
    with begin_immediate(finance.engine()) as conn:
        rules.categorize(
            conn, into, precise, proposal_id=None, created_at="2026-10-06T00:00:00.000Z"
        )
    assert shown(into) == ("remboursements", "remboursements")


def test_pocket_transfer_after_a_top_up_of_the_same_amount(finance: FinanceDomain) -> None:
    """BCF → compte Revolut → poche, le même montant le même jour : le débit de la BCF ne rend
    pas le virement compte → poche ambigu. Deux poches créditées du même montant, si."""
    without_seed_rules(finance)
    bcf = add_account(finance)
    rev = add_ref(finance, "revolut:CHF", "cash", "Revolut")
    car = add_ref(finance, "revolut:CHF:poche-1", "cash", "Voiture")
    trip = add_ref(finance, "revolut:CHF:poche-3", "cash", "Vacances")
    with begin_immediate(finance.engine()) as conn:
        top_up = _entry(conn, bcf, "2026-10-05", -80_000, iban=REVOLUT_IBAN, counterparty="Revolut")
        landed = _entry(conn, rev, "2026-10-05", 80_000, label="Top-up")
        out = _entry(conn, rev, "2026-10-05", -80_000, label="To pocket")
        into = _entry(conn, car, "2026-10-05", 80_000, label="From CHF")
        # le même montant vers deux poches le même jour : on ne devine pas
        _entry(conn, rev, "2026-10-20", -10_000, label="To pocket")
        _entry(conn, car, "2026-10-20", 10_000, label="From CHF")
        _entry(conn, trip, "2026-10-20", 10_000, label="From CHF")
        rules.categorize(
            conn,
            top_up,
            rules.Rule("system-transfer-own", "search_text", "revolut", "any", "transfer-own", 1),
            proposal_id=None,
            created_at="2026-10-05T00:00:00.000Z",
        )
    finance.refresh_derived()
    links = set(rows(finance, "SELECT debit_seq, credit_seq FROM transfer_links"))
    assert (out, into) in links
    assert (top_up, landed) in links
    assert len(links) == 2


RAIFFEISEN_IBAN = "CH3880808001234567890"  # clearing Raiffeisen, numéro fictif


def test_raiffeisen_camt_and_transfer_from_bcf(finance: FinanceDomain) -> None:
    """Raiffeisen exporte le même camt.053 (souvent en .04) : un compte déclaré avec son IBAN
    suffit, et le virement BCF → Raiffeisen s'apparie par les IBAN."""
    without_seed_rules(finance)
    ready_account(finance, 100_000)
    with begin_immediate(finance.engine()) as conn:
        raif = catalog.add_account(
            conn, institution="Raiffeisen", name="Épargne", iban=RAIFFEISEN_IBAN
        )
    open_account(finance, raif, "2026-09-30", 0)
    day = date(2026, 10, 5)
    out = Stmt(
        Decimal("1000.00"),
        day,
        [Tx("400.00", True, day, counterparty="Moi", counterparty_iban=RAIFFEISEN_IBAN)],
    )
    arrival = Stmt(
        Decimal("0.00"),
        day,
        [Tx("400.00", False, date(2026, 10, 6), counterparty="Moi", counterparty_iban=IBAN)],
        iban=RAIFFEISEN_IBAN,
        stmt_id="RAIF-1",
    )
    report = finance.importer.process(
        [Incoming("bcf.xml", camt053(out)), Incoming("raiffeisen.xml", camt053(arrival, "04"))]
    )
    assert [s.status for s in report.statements] == ["applied", "applied"]
    finance.refresh_derived()
    assert rows(finance, "SELECT method FROM transfer_links") == [("iban",)]
    with finance.engine().connect() as conn:
        v = valuation.value_at(conn, "2026-10-06")
    assert v.by_envelope["cash"] == 100_000


def test_recurring_detection(finance: FinanceDomain) -> None:
    without_seed_rules(finance)
    bcf = add_account(finance, budget_account=True)
    start = date(2026, 1, 5)
    with begin_immediate(finance.engine()) as conn:
        for m in range(10):
            on = recurring.add_months(start, m)
            _entry(conn, bcf, on.isoformat(), -1790, counterparty=f"NETFLIX.COM {m}1234")
        for w in range(20):  # courses : montants variables, pas un abonnement
            on = date(2026, 5, 1) + timedelta(days=7 * w)
            _entry(conn, bcf, on.isoformat(), -(5_000 + 1_300 * (w % 4)), counterparty="Migros")
        _entry(conn, bcf, "2024-11-15", -48_000, counterparty="NOTPROVIDED", label="Assurance RC")
        _entry(conn, bcf, "2025-11-14", -49_000, counterparty="NOTPROVIDED", label="Assurance RC")
        # arrêté : trois mois puis plus rien
        for m in range(3):
            _entry(
                conn,
                bcf,
                recurring.add_months(date(2025, 6, 1), m).isoformat(),
                -999,
                counterparty="Salle de sport",
            )
        recurring.refresh(conn, date(2026, 10, 27))
    found = {
        r[0]: r[1:]
        for r in rows(
            finance, "SELECT label, cadence, amount_minor, next_date, active FROM recurring"
        )
    }
    assert found["NETFLIX.COM 91234"] == ("monthly", -1790, "2026-11-05", 1)
    assert found["Assurance RC"] == ("yearly", -48_500, "2026-11-14", 1)
    assert found["Salle de sport"][0] == "monthly"
    assert found["Salle de sport"][3] == 0
    assert "Migros" not in found
    with finance.engine().connect() as conn:
        full = recurring.listing(conn, date(2026, 10, 27), aggregates_only=False)
        agg = recurring.listing(conn, date(2026, 10, 27), aggregates_only=True)
    assert full["count"] == 2
    assert full["due_30d"] == 2
    assert full["monthly_total"] == [{"minor": 1790 + 4042, "currency": "CHF", "display": "58.32"}]
    assert "items" not in agg
    assert agg["monthly_total"] == []


def test_recurring_helpers() -> None:
    assert recurring.add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert recurring.merchant_key("SPOTIFY P1234AB", "") == "spotify"
    assert recurring.display("NOTPROVIDED", "Loyer") == "Loyer"
    assert recurring.monthly(-12_000, "CHF", "yearly") == 1_000


# --- routes ------------------------------------------------------------------------------------


@pytest.fixture
def ctx(tmp_path: Path) -> Iterator[HubContext]:
    settings = finance_settings(tmp_path)
    hub = HubContext.build(settings, Registry([FinanceDomain(settings)]))
    hub.migrate_all()
    yield hub
    hub.dispose()


def test_routes(ctx: HubContext) -> None:
    with ctx.core.engine.begin() as conn:
        _i, app_secret = tokens.create(conn, "t", ["finance:read"], "system:test")
        _i, agg_secret = tokens.create(conn, "a", ["finance:aggregates"], "system:test")
    read = {"Authorization": f"Bearer {app_secret}"}
    agg = {"Authorization": f"Bearer {agg_secret}"}
    with TestClient(create_app(ctx), base_url="https://hub.example.ts.net") as client:
        r = client.get("/api/finance/lookthrough?dimension=sector", headers=agg)
        assert r.status_code == 200
        assert r.json()["items"] == []
        bad = client.get("/api/finance/lookthrough?dimension=planet", headers=agg)
        assert bad.status_code in (400, 422)
        assert client.get("/api/finance/recurring", headers=read).json()["items"] == []
        assert "items" not in client.get("/api/finance/recurring", headers=agg).json()
        t = client.get("/api/finance/transfers", headers=agg).json()
        assert t["pairs"] == 0
        assert "unmatched_items" not in t
        assert client.get("/api/finance/transfers", headers=read).json()["unmatched_items"] == []
        k = client.get("/api/finance/kpis", headers=agg).json()
        assert k["unmatched_transfers"] == 0
        assert set(k["envelopes"]) >= {"titres", "crypto"}
