"""Codes d'opération posés par les importeurs propres à une institution (chantier « hub
générique », G3).

Un relevé camt.053 ou Enable Banking garde le code de la banque ; un importeur propre (VIAC,
IBKR) pose le sien, `<INSTITUTION>/<OPÉRATION>`. Ce que chaque code veut dire pour le reste du
domaine est déclaré ici, une fois : appariement des virements, versements au patrimoine,
versements au pilier 3a, et catégorie posée par sa règle système. Une nouvelle institution
ajoute ses codes ici, et ses règles système par une migration (le test de cohérence vérifie
que les deux concordent).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Code:
    prefix: str  # préfixe de `bank_tx_code`
    category: str  # catégorie de la règle système `system-<institution>-<opération>`
    transfer: bool = False  # versement entre mes comptes : apparié à son autre côté
    internal: bool = False  # achat, vente ou change chez le courtier : jamais apparié
    market: bool = False  # pas un apport : effet marché dans la valorisation
    pension_deposit: bool = False  # versement reçu par le prestataire du pilier 3a

    @property
    def rule_id(self) -> str:
        institution, operation = self.prefix.lower().split("/", 1)
        return f"system-{institution}-{operation}"


CODES: tuple[Code, ...] = (
    Code("VIAC/DEPOSIT", "transfer-own", transfer=True, pension_deposit=True),
    Code("VIAC/WITHDRAWAL", "transfer-own", transfer=True),
    Code("VIAC/TRADE", "transfer-titres", internal=True),
    Code("VIAC/INCOME", "rendement", market=True),
    Code("VIAC/FEE", "frais-placement", market=True),
    Code("IBKR/DEPOSIT", "transfer-own", transfer=True),
    Code("IBKR/TRADE", "transfer-titres", internal=True, market=True),
    Code("IBKR/FX", "transfer-own", internal=True, market=True),
    Code("IBKR/INCOME", "rendement", market=True),
    Code("IBKR/FEE", "frais-placement", market=True),
    # SwissBorg : le virement de la banque est catégorisé « Crypto », achat hors versements ; son
    # arrivée sur la plateforme n'est donc pas un apport non plus
    Code("SWISSBORG/DEPOSIT", "transfer-own", transfer=True, market=True),
    Code("SWISSBORG/WITHDRAWAL", "transfer-own", transfer=True, market=True),
    Code("SWISSBORG/TRADE", "transfer-titres", internal=True, market=True),
    Code("SWISSBORG/INCOME", "rendement", market=True),
    Code("SWISSBORG/FEE", "frais-placement", market=True),
)


def prefixes(**role: bool) -> tuple[str, ...]:
    """Préfixes des codes qui ont ce rôle, par exemple `prefixes(transfer=True)`."""
    return tuple(c.prefix for c in CODES if all(getattr(c, k) == v for k, v in role.items()))


def like_any(column: str, codes: tuple[str, ...]) -> str:
    """Condition SQL `column LIKE 'A%' OR …` (préfixes déclarés ici, jamais une saisie)."""
    return " OR ".join(f"{column} LIKE '{c}%'" for c in codes) or "0"
