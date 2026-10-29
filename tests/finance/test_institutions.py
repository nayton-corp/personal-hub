"""Codes d'opération des institutions (chantier « hub générique », G3) : la déclaration et les
règles système posées par les migrations concordent."""

from __future__ import annotations

from sqlalchemy import text

from hub.domains.finance.domain import FinanceDomain
from hub.domains.finance.patrimoine.app import transfers, valuation
from hub.domains.finance.registre.model import institutions
from tests.finance.test_app_reads import ctx, fin  # noqa: F401 - fixtures


def test_system_rules_match_the_declared_codes(fin: FinanceDomain) -> None:  # noqa: F811
    with fin.engine().connect() as conn:
        rows = conn.execute(
            text(
                "SELECT id, pattern, category_id FROM rules "
                "WHERE id LIKE 'system-%' AND field = 'bank_tx_code'"
            )
        ).fetchall()
    declared = {(c.rule_id, c.prefix, c.category) for c in institutions.CODES}
    assert {tuple(r) for r in rows} == declared


def test_roles_keep_the_previous_lists() -> None:
    assert transfers.TRANSFER_CODES == (
        "VIAC/DEPOSIT",
        "VIAC/WITHDRAWAL",
        "IBKR/DEPOSIT",
        "SWISSBORG/DEPOSIT",
        "SWISSBORG/WITHDRAWAL",
        "CRYPTO/RECEIVE",
        "CRYPTO/SEND",
        "EXCHANGE/DEPOSIT",
        "EXCHANGE/WITHDRAWAL",
    )
    assert valuation.NOT_DEPOSITS == (
        "VIAC/INCOME",
        "VIAC/FEE",
        "IBKR/TRADE",
        "IBKR/FX",
        "IBKR/INCOME",
        "IBKR/FEE",
        "SWISSBORG/DEPOSIT",
        "SWISSBORG/WITHDRAWAL",
        "SWISSBORG/TRADE",
        "SWISSBORG/INCOME",
        "SWISSBORG/FEE",
        "CRYPTO/RECEIVE",
        "CRYPTO/SEND",
        "CRYPTO/FEE",
        "EXCHANGE/DEPOSIT",
        "EXCHANGE/WITHDRAWAL",
        "EXCHANGE/TRADE",
        "EXCHANGE/INCOME",
        "EXCHANGE/FEE",
    )
    assert institutions.prefixes(internal=True) == (
        "VIAC/TRADE",
        "IBKR/TRADE",
        "IBKR/FX",
        "SWISSBORG/TRADE",
        "EXCHANGE/TRADE",
    )
    assert institutions.prefixes(pension_deposit=True) == ("VIAC/DEPOSIT",)
    assert institutions.like_any("c", ()) == "0"
