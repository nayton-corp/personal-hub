"""Répartition du patrimoine affiché (audit du 10/11, lot B) : un seul calcul côté serveur, le
périmètre de l'écran, les liquidités comptées, la part sûre, et une somme égale à la valeur."""

from __future__ import annotations

from sqlalchemy import text

from hub.domains.finance.domain import FinanceDomain
from hub.domains.finance.packs import ch
from hub.domains.finance.patrimoine.app import allocation, valuation
from hub.domains.finance.patrimoine.infra import composition
from hub.domains.finance.sources.infra.files import Incoming
from hub.platform.db import begin_immediate
from tests.finance.conftest import add_account, open_account
from tests.finance.test_wealth import WORLD, add_ref, market_doc

ON = "2026-10-27"
REAL = "CH0105994401"  # ISIN fictifs, forme valide
POSITIONS = (
    "date,account,instrument,name,kind,quantity,price,currency\n"
    f"2026-10-20,test:invest,{WORLD},Fonds Monde,etf,10,100,CHF\n"
    f"2026-10-20,test:invest,{REAL},Fonds immobilier,fund,3,100,CHF\n"
    "2026-10-20,test:invest,AAPL,Apple,stock,2,200,USD\n"
    "2026-10-20,test:crypto,ETH,,crypto,1.5,3000,CHF\n"
)
SECTORS = (
    "isin,dimension,bucket,weight_pct,on_date\n"
    f"{WORLD},sector,Technologie,33.333,2026-09-30\n"
    f"{WORLD},sector,Santé,33.333,2026-09-30\n"
    f"{WORLD},sector,Finance,23.334,2026-09-30\n"
)


def setup(finance: FinanceDomain) -> tuple[str, str]:
    """Un compte courant (1 234.56), un compte à découvert (−200), des titres et une crypto."""
    bank = add_account(finance)
    open_account(finance, bank, "2026-10-01", 123_456)
    card = add_account(finance, iban="CH5604835012345678009")
    open_account(finance, card, "2026-10-01", -20_000)
    invest = add_ref(finance, "test:invest", "securities")
    add_ref(finance, "test:crypto", "crypto")
    fx = {"on_date": "2026-10-20", "base": "USD", "quote": "CHF", "rate": "1", "source": "ecb"}
    finance.importer.process(
        [
            Incoming("fx.json", market_doc(fx=[fx])),
            Incoming("positions.csv", POSITIONS.encode()),
            Incoming("fiche.csv", SECTORS.encode()),
        ]
    )
    with begin_immediate(finance.engine()) as conn:
        conn.execute(
            text("UPDATE instruments SET asset_class = 'Immobilier Suisse' WHERE isin = :i"),
            {"i": REAL},
        )
    return bank.id, invest.id


def by_bucket(out: dict) -> dict[str, int]:  # type: ignore[type-arg]
    return {i["bucket"]: i["value"]["minor"] for i in out["items"]}


def test_the_allocation_is_the_displayed_wealth(finance: FinanceDomain) -> None:
    setup(finance)
    with finance.engine().connect() as conn:
        net = valuation.value_at(conn, ON).net_worth
        outs = [
            allocation.breakdown(conn, d, ON, ch.PACK) for d in ("sector", "region", "currency")
        ]
    for out in outs:
        # la somme des cases est le total au centime, et le total moins les dettes est la valeur
        assert sum(by_bucket(out).values()) == out["total"]["minor"]
        assert out["total"]["minor"] + out["owed"]["minor"] == net
        assert out["owed"]["minor"] == -20_000
    sector = by_bucket(outs[0])
    assert sector[allocation.CASH] == 123_456
    assert sector[composition.CRYPTO] == 450_000
    # 1000 de fonds : trois secteurs publiés, 10 % que la fiche ne détaille pas
    assert sector["Finance"] == 23_334
    assert sector[allocation.NOT_SPLIT] == 10_000
    assert sector["Secteur inconnu"] == 40_000  # l'action, sans fiche
    kinds = {i["bucket"]: (i["kind"], i["estimated"]) for i in outs[0]["items"]}
    assert kinds[allocation.CASH] == ("cash", False)
    assert kinds["Immobilier"] == ("named", True)  # tiré de la classe du fonds : estimé
    assert kinds["Technologie"] == ("named", False)
    # les liquidités nomment leur compte, pas un instrument
    cash = next(i for i in outs[0]["items"] if i["bucket"] == allocation.CASH)
    assert [(a["isin"], a["name"]) for a in cash["assets"]] == [(None, "BCF · Compte privé")]
    # part sûre : tout sauf l'immobilier estimé (300), le non réparti (100) et l'inconnu (400)
    total = outs[0]["total"]["minor"]
    assert outs[0]["covered"] == f"{1 - 80_000 / total:.4f}"
    assert outs[0]["compositions_since"] == "2026-09-30"
    # par devise : les liquidités vont dans la devise de leur compte
    assert by_bucket(outs[2])["CHF"] >= 123_456


def test_hidden_accounts_and_the_selection_follow_the_screen(finance: FinanceDomain) -> None:
    bank, invest = setup(finance)
    with finance.engine().connect() as conn:
        only = allocation.breakdown(conn, "sector", ON, ch.PACK, [f"{bank}|cash"])
        fund = allocation.breakdown(conn, "sector", ON, ch.PACK, [f"{invest}|{WORLD}"])
    assert by_bucket(only) == {allocation.CASH: 123_456}
    assert (only["owed"]["minor"], only["covered"]) == (0, "1.0000")
    assert fund["total"]["minor"] == 100_000
    assert allocation.CASH not in by_bucket(fund)
    with begin_immediate(finance.engine()) as conn:
        conn.execute(text("UPDATE accounts SET hidden = 1 WHERE id = :i"), {"i": invest})
    with finance.engine().connect() as conn:
        out = allocation.breakdown(conn, "sector", ON, ch.PACK)
    # un compte masqué sort de la répartition, comme du patrimoine affiché
    assert by_bucket(out) == {composition.CRYPTO: 450_000, allocation.CASH: 123_456}


def test_a_position_without_price_is_named_apart(finance: FinanceDomain) -> None:
    add_ref(finance, "crypto:phantom", "crypto", "Phantom")
    sol = {"kind": "crypto", "currency": "CHF", "source": "coingecko", "instrument": "SOL"}
    doc = market_doc(
        prices=[{**sol, "on_date": "2026-10-01", "price": "100"}],
        balances=[
            {"account": "crypto:phantom", "instrument": i, "on_date": "2026-10-06", "quantity": q}
            for i, q in [("SOL", "4"), ("ABC", "5")]  # ABC : sans cours
        ],
    )
    finance.importer.process([Incoming("market.json", doc)])
    with finance.engine().connect() as conn:
        out = allocation.breakdown(conn, "sector", ON, ch.PACK)
        empty = allocation.breakdown(conn, "sector", "2020-01-01", ch.PACK)
    assert [u["isin"] for u in out["unpriced"]] == ["CRYPTO:ABC"]
    assert by_bucket(out) == {composition.CRYPTO: 40_000}
    assert (empty["items"], empty["covered"], empty["unpriced"]) == ([], None, [])
