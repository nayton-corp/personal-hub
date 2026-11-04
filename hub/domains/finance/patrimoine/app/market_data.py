"""Lecture, une fois par calcul, des cours de change (registre/app/fx.py) et des parts, relevés
et cours des comptes à positions (model/positions.py) depuis la base."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import Connection, text

from hub.domains.finance.patrimoine.model import positions
from hub.domains.finance.registre.app.fx import FxTable as FxTable
from hub.domains.finance.registre.model import fx

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
        # cours : à date égale, la source triée en dernier l'emporte (rapport VIAC sur l'avis)
        prices: dict[str, list[positions.Price]] = {}
        for isin, on, price, ccy in conn.execute(
            text("SELECT isin, on_date, price, currency FROM prices ORDER BY on_date, source")
        ):
            prices.setdefault(isin, []).append((on, Decimal(price), str(ccy)))
        super().__init__(table or FxTable(conn), trades, reports, prices)
