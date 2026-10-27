"""Montants : entier signé en unités mineures et code ISO 4217. Jamais de flottant."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Context, Decimal, InvalidOperation, localcontext

# Copie de la table `currencies` ; la base reste la référence pour les domaines.
CURRENCY_EXPONENTS: dict[str, int] = {"CHF": 2, "EUR": 2, "USD": 2, "GBP": 2, "JPY": 0}

DECIMAL_CONTEXT = Context(prec=28, rounding=ROUND_HALF_EVEN)

_CODE = re.compile(r"^[A-Z]{3}$")


class CurrencyError(ValueError):
    pass


def exponent(currency: str) -> int:
    try:
        return CURRENCY_EXPONENTS[currency]
    except KeyError:
        raise CurrencyError(f"devise inconnue : {currency!r}") from None


@dataclass(frozen=True, slots=True)
class Money:
    minor: int
    currency: str

    def __post_init__(self) -> None:
        # bool est un int : on le refuse explicitement
        if not isinstance(self.minor, int) or isinstance(self.minor, bool):
            raise TypeError("Money.minor doit être un entier (unités mineures)")
        if not _CODE.match(self.currency):
            raise CurrencyError(f"code de devise invalide : {self.currency!r}")
        exponent(self.currency)

    @classmethod
    def zero(cls, currency: str) -> Money:
        return cls(0, currency)

    @classmethod
    def from_decimal(cls, amount: Decimal | str, currency: str) -> Money:
        """Convertit un montant décimal ('45.50') en unités mineures, arrondi au demi pair."""
        with localcontext(DECIMAL_CONTEXT):
            try:
                value = Decimal(amount)
            except InvalidOperation:
                raise ValueError(f"montant illisible : {amount!r}") from None
            if not value.is_finite():
                raise ValueError("montant non fini")
            scaled = value.scaleb(exponent(currency)).quantize(Decimal(1), ROUND_HALF_EVEN)
        return cls(int(scaled), currency)

    def to_decimal(self) -> Decimal:
        with localcontext(DECIMAL_CONTEXT):
            return Decimal(self.minor).scaleb(-exponent(self.currency))

    def display(self) -> str:
        """'-45.50' : point décimal, sans séparateur de milliers ; la mise en forme locale est
        l'affaire de l'app."""
        exp = exponent(self.currency)
        sign = "-" if self.minor < 0 else ""
        units, cents = divmod(abs(self.minor), 10**exp)
        return f"{sign}{units}.{cents:0{exp}d}" if exp else f"{sign}{units}"

    def to_api(self) -> dict[str, int | str]:
        return {"minor": self.minor, "currency": self.currency, "display": self.display()}

    def _same(self, other: Money) -> None:
        if self.currency != other.currency:
            raise CurrencyError(f"devises différentes : {self.currency} et {other.currency}")

    def __add__(self, other: Money) -> Money:
        self._same(other)
        return Money(self.minor + other.minor, self.currency)

    def __sub__(self, other: Money) -> Money:
        self._same(other)
        return Money(self.minor - other.minor, self.currency)

    def __neg__(self) -> Money:
        return Money(-self.minor, self.currency)

    def __lt__(self, other: Money) -> bool:
        self._same(other)
        return self.minor < other.minor

    def __le__(self, other: Money) -> bool:
        self._same(other)
        return self.minor <= other.minor


def quantize(value: Decimal, places: int) -> Decimal:
    """Arrondi d'affichage ou de conversion, au demi pair."""
    with localcontext(DECIMAL_CONTEXT):
        return value.quantize(Decimal(1).scaleb(-places), ROUND_HALF_EVEN)
