"""Le cœur ne connaît aucun domaine (chantier S1) : ni source, ni banque, ni notion de finance.

Ce qu'un domaine apporte au cœur (connecteurs, modules par pays, reprise des anciennes
connexions) passe par les points d'entrée du paquet, lus par `hub.core.registry.contributions`.
Un mot de la liste qui revient dans `hub/core` (hors migrations, figées) fait échouer ce test :
la donnée va dans le domaine, le cœur la reçoit.
"""

import re
from pathlib import Path

from hub.core import connectors, profile

CORE = Path(__file__).resolve().parents[1] / "hub" / "core"
FINANCE = re.compile(
    r"\b(iban|camt|pillar\w*|3a|wallets?|portefeuilles?|crypto|bcf|viac|revolut|ibkr|binance"
    r"|kucoin|coinbase|swissborg|enable[ _]banking|aspsp\w*)\b",
    re.IGNORECASE,
)


def test_core_names_no_finance_source() -> None:
    found = [
        f"{path.relative_to(CORE)}:{n}: {m.group(0)}"
        for path in sorted(CORE.rglob("*.py"))
        if "migrations" not in path.parts
        for n, line in enumerate(path.read_text().splitlines(), 1)
        for m in [FINANCE.search(line)]
        if m
    ]
    assert found == [], "le cœur nomme un domaine : déplacer la donnée dans le domaine"


def test_the_finance_contributes_through_entry_points() -> None:
    assert "enable_banking" in connectors.names()
    assert connectors.get("market") is not None
    assert "pillar3a" in profile.country_modules()["CH"]
