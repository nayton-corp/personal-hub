"""Lecture, une fois par calcul, des cours de change (model/fx.py) et des parts, relevés et cours
des comptes à positions (model/positions.py) depuis la base."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from sqlalchemy import Connection, text

from hub.domains.finance.patrimoine.model import fx, positions
from hub.kernel.money import base_currency

Line = positions.Line


class FxTable(fx.FxRates):
    """Cours vers la devise de base, lus en base : toutes les devises connues, ou `currencies`."""

    def __init__(self, conn: Connection, currencies: Sequence[str] | None = None) -> None:
        if currencies is None:
            currencies = list(conn.execute(text("SELECT code FROM currencies")).scalars())
        base = base_currency()
        rates: dict[str, list[tuple[str, Decimal]]] = {}
        for ccy in sorted(set(currencies) - {base}):
            rows = conn.execute(
                text(
                    "SELECT on_date, rate FROM fx_rates WHERE base = :b AND quote = :q "
                    "ORDER BY on_date, source"
                ),
                {"b": ccy, "q": base},
            ).fetchall()
            rates[ccy] = [(r[0], Decimal(r[1])) for r in rows]
        super().__init__(base, rates)


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
