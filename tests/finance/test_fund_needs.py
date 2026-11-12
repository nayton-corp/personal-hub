"""Fonds dont le hub demande la composition au collecteur « market » : les fonds détenus (un ETF
rangé parmi les actions compris, une action ou une crypto non), la date de leur dernière
composition, et « stable » pour un fonds entièrement dans une seule case."""

from __future__ import annotations

from hub.domains.finance.domain import FinanceDomain
from hub.domains.finance.patrimoine.app import fund_needs
from hub.domains.finance.sources.infra.files import Incoming
from tests.finance.test_allocation import ON, REAL, setup
from tests.finance.test_wealth import WORLD

VOO = "US9229083632"


def test_held_funds_and_the_date_of_their_composition(finance: FinanceDomain) -> None:
    setup(finance)  # WORLD (etf, secteurs au 30.09), REAL (fund, sans fiche), AAPL, ETH
    as_stock = (
        "date,account,instrument,name,kind,quantity,price,currency\n"
        f"2026-10-20,test:invest,{VOO},Vanguard S&P 500 ETF,stock,1,500,USD\n"
    )
    finance.importer.process([Incoming("voo.csv", as_stock.encode())])
    with finance.engine().connect() as conn:
        assert fund_needs.needs(conn, ON) == [
            {"isin": REAL, "since": None, "stable": False},
            {"isin": WORLD, "since": "2026-09-30", "stable": False},
            {"isin": VOO, "since": None, "stable": False},  # un ETF que le courtier dit action
        ]
    # ce que le collecteur reçoit : des ISIN et des dates, rien d'autre
    asked = finance.collector_needs("market")
    assert [n["isin"] for n in asked["funds"]] == [REAL, WORLD, VOO]
    assert {k for n in asked["funds"] for k in n} == {"isin", "since", "stable"}
    assert finance.collector_needs("bcf") == {}


def test_a_fund_in_a_single_box_is_stable(finance: FinanceDomain) -> None:
    setup(finance)
    whole = (
        "isin,dimension,bucket,weight_pct,on_date\n"
        f"{REAL},sector,Immobilier,100,2026-10-30\n"
        f"{REAL},region,Suisse,100,2026-10-30\n"
        f"{REAL},currency,CHF,100.00,2026-10-30\n"
    )
    finance.importer.process([Incoming("immobilier.csv", whole.encode())])
    with finance.engine().connect() as conn:
        found = {n["isin"]: n for n in fund_needs.needs(conn, ON)}
    assert found[REAL] == {"isin": REAL, "since": "2026-10-30", "stable": True}
    assert found[WORLD]["stable"] is False  # trois secteurs


def test_a_fund_is_known_by_its_kind_or_its_name() -> None:
    assert fund_needs.is_fund("etf", "Fonds Monde")
    assert fund_needs.is_fund("stock", "iShares Core S&P 500 UCITS ETF")
    assert fund_needs.is_fund("other", "UBS Fonds Immobilier Suisse")
    assert not fund_needs.is_fund("stock", "Apple")
    assert not fund_needs.is_fund("crypto", "Index Coop")
    assert not fund_needs.is_fund(None, None)
