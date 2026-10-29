"""Commerçant lu dans les libellés bancaires (gabarits BCF, données fictives)."""

from __future__ import annotations

import pytest

from hub.core.text import normalize
from hub.domains.finance.merchant import key


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("Paiement 12.03.2025 14:32 Zorglub Fribourg Pér Numéro de carte: 1234******1", "zorglub"),
        ("Paiement 12.03.2025 14:32 ZORGLUB-1234 BULLE Numéro de carte: 1", "zorglub"),
        ("Paiement 01.02.2026 08:01 Zorglub Café Frib Numéro de carte: 1", "zorglub cafe"),
        ("Paiement 01.02.2026 08:01 Garage de Bulle Numéro de carte: 1", "garage"),
        ("Paiement 01.02.2026 08:01 Bidule 1234 V Numéro de carte: 1", "bidule"),
        ("Paiement - BIDULE SHOP, LAUSANNE - 12:00:00 - N° carte xxxxxxxxxxxx1234", "bidule shop"),
        (
            "Paiement - BIDULE.COM, 0800123456 - 12:00:00 - N° carte 1234 USD 9.99 au cours de "
            "0.9 = CHF 9.00",
            "bidule.com",
        ),
        ("Remboursement manuel - BIDULE, BERN - 01.01.2020 10:00 - N° carte x", "bidule"),
        ("Débit direct Maestro 10:00 Fictif Market Marly Numéro de carte: 1234", "fictif market"),
        ("Retrait BM 10:00 Gare Numéro de carte: 1", "retrait bm"),
        ("Prélèvement bancomat GARE 01.01.20 10:00 CHF  N° de carte: 1", "prelevement bancomat"),
        ("Débit TWINT DUPONT, JEAN, +41790000000 1234567890123456", "debit twint dupont, jean"),
        ("Débit TWINT ZORGLUB SHOP 1234567890123456", "debit twint zorglub shop"),
        ("Crédit TWINT DUPONT, JEAN, +41790000000 1234567890123456", "credit twint dupont, jean"),
        ("Ordre permanent Régie Fictive", None),
        ("", None),
    ],
)
def test_merchant_key(label: str, expected: str | None) -> None:
    found = key(label)
    assert found == expected
    # motif d'une règle : toujours un morceau du texte de l'écriture
    if found:
        assert found in normalize(label)
