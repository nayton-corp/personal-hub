from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from hub.core.money import CurrencyError, Money, quantize


def test_display_and_api() -> None:
    assert Money(-4550, "CHF").display() == "-45.50"
    assert Money(5, "CHF").display() == "0.05"
    assert Money(1200, "JPY").display() == "1200"
    assert Money(-4550, "CHF").to_api() == {"minor": -4550, "currency": "CHF", "display": "-45.50"}


def test_from_decimal_rounds_half_even() -> None:
    assert Money.from_decimal("0.125", "CHF").minor == 12
    assert Money.from_decimal("0.135", "CHF").minor == 14
    assert Money.from_decimal(Decimal("-45.5"), "CHF").minor == -4550
    assert Money.from_decimal("12", "JPY").minor == 12


@pytest.mark.parametrize("bad", ["abc", "NaN", "Infinity"])
def test_from_decimal_rejects_garbage(bad: str) -> None:
    with pytest.raises(ValueError):  # noqa: PT011
        Money.from_decimal(bad, "CHF")


def test_rejects_non_integer_and_unknown_currency() -> None:
    with pytest.raises(TypeError):
        Money(Decimal("1.5"), "CHF")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        Money(True, "CHF")
    with pytest.raises(CurrencyError):
        Money(1, "XXX")
    with pytest.raises(CurrencyError):
        Money(1, "chf")


def test_arithmetic_refuses_mixed_currencies() -> None:
    assert Money(100, "CHF") + Money(50, "CHF") == Money(150, "CHF")
    assert Money(100, "CHF") - Money(150, "CHF") == Money(-50, "CHF")
    assert -Money(1, "EUR") == Money(-1, "EUR")
    assert Money(1, "CHF") < Money(2, "CHF")
    assert Money(2, "CHF") <= Money(2, "CHF")
    assert Money.zero("USD").minor == 0
    with pytest.raises(CurrencyError):
        _ = Money(1, "CHF") + Money(1, "EUR")


def test_quantize() -> None:
    assert quantize(Decimal("1.005"), 2) == Decimal("1.00")
    assert quantize(Decimal("1.015"), 2) == Decimal("1.02")


@given(st.integers(min_value=-(10**15), max_value=10**15))
def test_roundtrip_through_decimal(minor: int) -> None:
    m = Money(minor, "CHF")
    assert Money.from_decimal(m.to_decimal(), "CHF") == m
    assert Money.from_decimal(m.display(), "CHF") == m
