"""Les seuils de la finance viennent des réglages `[finance]`, en devise de base (audit m2)."""

from __future__ import annotations

from decimal import Decimal

from hub.domains.finance.thresholds import Thresholds


def test_defaults_follow_the_base_currency() -> None:
    chf = Thresholds.from_section({}, "CHF")
    assert (chf.tolerance_minor, chf.stale_account_days, chf.price_stale_days("crypto")) == (
        100,
        45,
        3,
    )
    assert chf.price_stale_days("cash") == 14
    assert Thresholds.from_section({}, "JPY").tolerance_minor == 1  # un yen, pas cent


def test_settings_override_each_threshold() -> None:
    th = Thresholds.from_section(
        {
            "tolerance_minor": 250,
            "stale_account_days": 10,
            "stale_price_days": 2,
            "stale_crypto_price_days": 1,
            "stale_fx_days": 3,
            "quantity_epsilon": "1e-6",
        },
        "CHF",
    )
    assert (th.tolerance_minor, th.stale_account_days, th.stale_fx_days) == (250, 10, 3)
    assert (th.price_stale_days("cash"), th.price_stale_days("crypto")) == (2, 1)
    assert th.quantity_epsilon == Decimal("1e-6")
