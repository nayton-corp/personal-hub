"""Les cours de change vers la devise de base, lus en base une fois par calcul (model/fx.py) :
le patrimoine, le budget (dépenses en devise, audit C3) et le rapprochement lisent la même
table."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from sqlalchemy import Connection, text

from hub.domains.finance.registre.model.fx import FxRates
from hub.kernel.money import base_currency


class FxTable(FxRates):
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
