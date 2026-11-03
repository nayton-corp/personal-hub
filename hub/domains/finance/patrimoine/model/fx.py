"""Cours de change vers la devise de base, sans base : des listes datées par devise, lues une
fois par calcul. Le taux d'un jour est le dernier connu ce jour-là ou avant ; son âge se dit au
rapprochement (`stale_fx`), jamais caché ; sans aucun taux, None, jamais 0."""

from __future__ import annotations

import bisect
from collections.abc import Mapping, Sequence
from decimal import Decimal, localcontext

from hub.kernel.money import DECIMAL_CONTEXT, Money


class FxRates:
    """Cours vers la devise de base, par devise, triés par date."""

    def __init__(self, base: str, rates: Mapping[str, Sequence[tuple[str, Decimal]]]) -> None:
        self.base = base
        self._rates: dict[str, list[tuple[str, Decimal]]] = {
            ccy: sorted(rows) for ccy, rows in rates.items() if ccy != base
        }
        self._dates = {ccy: [d for d, _r in rows] for ccy, rows in self._rates.items()}

    @property
    def currencies(self) -> frozenset[str]:
        return frozenset(self._rates)

    def dated(self, currency: str, on_date: str) -> tuple[str, Decimal] | None:
        """(jour du change, taux) utilisé pour `on_date` : le dernier connu ce jour-là ou avant."""
        if currency == self.base:
            return on_date, Decimal(1)
        k = bisect.bisect_right(self._dates.get(currency, []), on_date)
        return self._rates[currency][k - 1] if k else None

    def rate(self, currency: str, on_date: str) -> Decimal | None:
        known = self.dated(currency, on_date)
        return None if known is None else known[1]

    def convert(self, amount: Decimal, currency: str, on_date: str) -> int | None:
        """Montant décimal dans `currency` → centimes de la devise de base, ou None sans cours."""
        rate = self.rate(currency, on_date)
        if rate is None:
            return None
        with localcontext(DECIMAL_CONTEXT):
            return Money.from_decimal(amount * rate, self.base).minor

    def to_base(self, minor: int, currency: str, on_date: str) -> int | None:
        if currency == self.base:
            return minor
        return self.convert(Money(minor, currency).to_decimal(), currency, on_date)
