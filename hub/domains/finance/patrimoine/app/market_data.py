"""Lecture, une fois par calcul, des cours de change (registre/app/fx.py) et des parts, relevés
et cours des comptes à positions (model/positions.py) depuis la base."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import Connection, text

from hub.domains.finance.patrimoine.app import assets
from hub.domains.finance.patrimoine.model import positions
from hub.domains.finance.registre.app.fx import FxTable as FxTable
from hub.domains.finance.registre.model import fx
from hub.kernel.money import exponent

Line = positions.Line


class Positions(positions.Positions):
    """Parts, relevés de positions et cours de tous les comptes à positions, lus une fois."""

    def __init__(self, conn: Connection, table: fx.FxRates | None = None) -> None:
        trades: dict[str, list[positions.Trade]] = {}
        for account_id, on, isin, qty in conn.execute(
            text(
                "SELECT account_id, trade_date, isin, quantity FROM trades ORDER BY trade_date, seq"
            )
        ):
            trades.setdefault(account_id, []).append((on, isin, Decimal(qty)))
        # relevés : account -> [(date, {isin: (parts, valeur, devise)})] triés
        snaps: dict[str, dict[str, dict[str, tuple[Decimal, int, str]]]] = {}
        for account_id, on, isin, qty, value, ccy in conn.execute(
            text(
                "SELECT account_id, on_date, isin, quantity, value_minor, currency FROM holdings "
                "ORDER BY seq"  # à date égale, le relevé le plus récent l'emporte
            )
        ):
            snaps.setdefault(account_id, {}).setdefault(on, {})[isin] = (
                Decimal(qty),
                int(value),
                str(ccy),
            )
        reports = {a: sorted(by_date.items()) for a, by_date in snaps.items()}
        # cours : à date égale, la source la plus sûre (`assets.PRICE_SOURCES`) vient en dernier
        # et l'emporte
        prices: dict[str, list[positions.Price]] = {}
        for isin, on, price, ccy in conn.execute(
            text(
                "SELECT isin, on_date, price, currency FROM prices "  # noqa: S608 - constante
                f"ORDER BY on_date, {assets.price_rank()} DESC, source"
            )
        ):
            prices.setdefault(isin, []).append((on, Decimal(price), str(ccy)))
        # prix des opérations (montant ÷ parts, en devise du compte), faute de cours
        paid: dict[str, list[positions.Price]] = {}
        for isin, on, qty, amount, ccy in conn.execute(
            text(
                "SELECT isin, trade_date, quantity, amount_minor, currency FROM trades "
                "WHERE amount_minor != 0 ORDER BY trade_date, seq"
            )
        ):
            q = abs(Decimal(qty))
            if q:
                unit = abs(Decimal(int(amount))) / 10 ** exponent(str(ccy)) / q
                paid.setdefault(isin, []).append((on, unit, str(ccy)))
        super().__init__(table or FxTable(conn), trades, reports, prices, paid)
