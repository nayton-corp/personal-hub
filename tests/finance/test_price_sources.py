"""m13 : à date égale, la source d'un cours qui fait foi est déclarée (`assets.PRICE_SOURCES`),
plus l'ordre alphabétique de son nom."""

from __future__ import annotations

from decimal import Decimal

from hub.domains.finance.domain import FinanceDomain
from hub.domains.finance.patrimoine.app import assets, market_data, price_history
from hub.platform.db import begin_immediate

ISIN = "IE00TEST00001"


def test_the_custodian_report_beats_the_market_close_and_the_trade(
    finance: FinanceDomain,
) -> None:
    with begin_immediate(finance.engine()) as conn:
        assets.upsert_instrument(conn, ISIN, "Fonds", kind="fund", currency="CHF")
        for source, price in (
            ("yahoo", "101"),
            ("viac_notice", "103"),
            ("viac_report", "102"),
            ("zzz_unknown", "104"),
        ):
            assert assets.add_price(conn, ISIN, "2026-03-31", Decimal(price), "CHF", source, None)
        assert assets.add_price(conn, ISIN, "2026-03-30", Decimal("99"), "CHF", "binance", None)
    with finance.engine().connect() as conn:
        assert assets.price_at(conn, ISIN, "2026-03-31") == (Decimal("102"), "CHF")
        assert assets.price_at(conn, ISIN, "2026-03-30") == (Decimal("99"), "CHF")
        series = market_data.Positions(conn).prices[ISIN]
        history = price_history.history(conn, ISIN, None, "2026-12-31")
    assert series[-1] == ("2026-03-31", Decimal("102"), "CHF")
    assert history["items"][-1]["price"] == "102"


def test_a_known_kind_is_kept_only_other_is_filled(finance: FinanceDomain) -> None:
    with begin_immediate(finance.engine()) as conn:
        assets.upsert_instrument(conn, ISIN, "Fonds", kind="other")
        assets.upsert_instrument(conn, ISIN, None, kind="fund")
        assets.upsert_instrument(conn, ISIN, None, kind="stock")
        kind = conn.execute(
            __import__("sqlalchemy").text("SELECT kind FROM instruments WHERE isin = :i"),
            {"i": ISIN},
        ).scalar_one()
    assert kind == "fund"
