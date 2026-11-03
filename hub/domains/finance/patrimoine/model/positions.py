"""Parts, relevés et cours des comptes à positions, sans base : la seule règle qui donne la
valeur d'une position (docs/finance-politique.md, « Valeur »).

Les parts à une date sont celles du dernier relevé, plus les achats et ventes postérieurs. Une
position vaut ses parts fois le dernier cours connu, converti au change du jour ; la valeur
annoncée par le relevé ne sert que le jour du relevé, pour des parts que rien n'a bougées, et si
elle est positive. Sans cours, ou sans change pour sa devise, la position n'a pas de valeur :
`price` est None, jamais 0 en silence.
"""

from __future__ import annotations

import bisect
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal, localcontext

from hub.domains.finance.patrimoine.model.fx import FxRates
from hub.kernel.money import DECIMAL_CONTEXT

Report = tuple[
    str, dict[str, tuple[Decimal, int, str]]
]  # (jour, {instrument: (parts, valeur, devise)})
Trade = tuple[str, str, Decimal]  # (jour, instrument, parts signées)
Price = tuple[str, Decimal, str]  # (jour, cours, devise)


@dataclass(frozen=True)
class Line:
    """Une position valorisée d'un compte à positions."""

    account_id: str
    isin: str
    quantity: Decimal
    price: Decimal | None  # dans `currency` ; None sans cours ou sans change
    price_date: str | None
    value: int  # centimes de la devise de base ; 0 sans cours
    currency: str  # devise du cours


@dataclass
class Holding:
    """Les parts d'un compte, tenues jour après jour (`advance`) ou posées à une date
    (`Positions.quantities`) : dernier relevé, sa date, les instruments bougés depuis."""

    reports: Sequence[Report]
    trades: Sequence[Trade]
    ri: int = 0
    ti: int = 0
    qty: dict[str, Decimal] = field(default_factory=dict)
    base: dict[str, tuple[Decimal, int, str]] = field(default_factory=dict)
    since: str = ""
    moved: set[str] = field(default_factory=set)

    def advance(self, on: str) -> None:
        """Jusqu'au jour `on`, d'un trait ou jour après jour : le dernier relevé fait les parts,
        les opérations postérieures (jusqu'à `on`) les bougent ; une opération du jour même du
        relevé y est déjà comptée."""
        while self.ri < len(self.reports) and self.reports[self.ri][0] <= on:
            self.since, self.base = self.reports[self.ri]
            self.qty = {isin: q for isin, (q, _v, _c) in self.base.items()}
            self.moved = set()
            self.ri += 1
        with localcontext(DECIMAL_CONTEXT):
            while self.ti < len(self.trades) and self.trades[self.ti][0] <= on:
                d, isin, q = self.trades[self.ti]
                if self.since < d:
                    self.qty[isin] = self.qty.get(isin, Decimal(0)) + q
                    self.moved.add(isin)
                self.ti += 1


class Positions:
    """Parts, relevés de positions et cours de tous les comptes à positions."""

    def __init__(
        self,
        fx: FxRates,
        trades: Mapping[str, Sequence[Trade]],
        reports: Mapping[str, Sequence[Report]],
        prices: Mapping[str, Sequence[Price]],
    ) -> None:
        self.fx = fx
        self.trades = {a: list(t) for a, t in trades.items()}
        self.reports = {a: list(r) for a, r in reports.items()}
        self.prices = {i: list(p) for i, p in prices.items()}
        self._dates = {i: [d for d, _p, _c in p] for i, p in self.prices.items()}

    @property
    def accounts(self) -> set[str]:
        return set(self.trades) | set(self.reports)

    def holding(self, account_id: str) -> Holding:
        return Holding(self.reports.get(account_id, []), self.trades.get(account_id, []))

    def price(self, isin: str, on_date: str) -> Price | None:
        k = bisect.bisect_right(self._dates.get(isin, []), on_date)
        return self.prices[isin][k - 1] if k else None

    def worth(self, isin: str, quantity: Decimal, on_date: str) -> int | None:
        """Ce que valent `quantity` parts au dernier cours connu, en centimes de la devise de
        base ; None sans cours ou sans change."""
        known = self.price(isin, on_date)
        if known is None:
            return None
        _d, price, ccy = known
        with localcontext(DECIMAL_CONTEXT):
            return self.fx.convert(quantity * price, ccy, on_date)

    def quantities(
        self, account_id: str, on_date: str
    ) -> tuple[dict[str, Decimal], dict[str, tuple[Decimal, int, str]], str, set[str]]:
        """(parts par instrument, dernier relevé, sa date, instruments bougés depuis)."""
        h = self.holding(account_id)
        h.advance(on_date)
        return h.qty, h.base, h.since, h.moved

    def valued(self, account_id: str, h: Holding, on_date: str) -> list[Line]:
        """Les positions du compte telles que `h` les tient, valorisées à `on_date`."""
        out = []
        with localcontext(DECIMAL_CONTEXT):
            for isin in sorted(h.qty):
                q = h.qty[isin]
                if q == 0:
                    continue
                known = self.price(isin, on_date)
                if known is None:
                    out.append(Line(account_id, isin, q, None, None, 0, self.fx.base))
                    continue
                d, price, ccy = known
                if isin in h.base and isin not in h.moved and d == h.since and h.base[isin][1]:
                    # valeur du relevé, au centime près, convertie au change de la date ; un
                    # relevé à 0 pour des parts tenues (SwissBorg) n'annonce pas de valeur
                    _q, reported, rccy = h.base[isin]
                    value = self.fx.to_base(reported, rccy, on_date)
                else:
                    value = self.fx.convert(q * price, ccy, on_date)
                if value is None:  # cours sans change vers la devise de base
                    out.append(Line(account_id, isin, q, None, d, 0, ccy))
                    continue
                out.append(Line(account_id, isin, q, price, d, value, ccy))
        return out

    def lines(self, account_id: str, on_date: str) -> list[Line]:
        h = self.holding(account_id)
        h.advance(on_date)
        return self.valued(account_id, h, on_date)
