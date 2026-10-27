"""Ce que produisent les parseurs VIAC : des objets, jamais d'écriture en base.

Montants et quantités en `Decimal` exact (lus dans le texte, sans flottant) ; les dates en
AAAA-MM-JJ. Un montant d'avis est toujours positif : le sens vient du type d'opération.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict

NoticeKind = Literal["buy", "sell", "dividend", "interest", "fee", "deposit", "withdrawal"]
# effet de chaque type sur les liquidités du portefeuille
CASH_SIGN: dict[str, int] = {
    "buy": -1,
    "sell": 1,
    "dividend": 1,
    "interest": 1,
    "fee": -1,
    "deposit": 1,
    "withdrawal": -1,
}
# code porté par l'écriture : les règles système le reconnaissent, la valorisation aussi
# (`VIAC/INCOME` et `VIAC/FEE` sont du rendement, pas des apports)
TX_CODE: dict[str, str] = {
    "buy": "VIAC/TRADE/BUY",
    "sell": "VIAC/TRADE/SELL",
    "dividend": "VIAC/INCOME/DIVIDEND",
    "interest": "VIAC/INCOME/INTEREST",
    "fee": "VIAC/FEE",
    "deposit": "VIAC/DEPOSIT",
    "withdrawal": "VIAC/WITHDRAWAL",
}
LABEL: dict[str, str] = {
    "buy": "Achat de parts",
    "sell": "Vente de parts",
    "dividend": "Dividende",
    "interest": "Intérêts",
    "fee": "Commission de gestion",
    "deposit": "Versement 3a",
    "withdrawal": "Retrait 3a",
}


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Notice(_Frozen):
    """Un avis d'opération VIAC (Fondation Terzo) : une opération par document."""

    kind: NoticeKind
    portfolio: str  # 3.123.456.789.01
    value_date: str
    amount: Decimal  # CHF comptabilisé, positif
    isin: str | None = None
    fund: str | None = None
    quantity: Decimal | None = None  # parts, positif
    price: Decimal | None = None  # cours unitaire, dans price_currency
    price_currency: str | None = None
    detail: str = ""

    @property
    def is_trade(self) -> bool:
        return self.kind in ("buy", "sell")


class Position(_Frozen):
    category: str | None  # 'Actions', 'Immobilier'…
    sub_class: str  # 'Actions Suisse'…
    currency: str  # devise de cotation
    quantity: Decimal
    name: str
    isin: str
    cost_price: Decimal  # prix initial unitaire, devise de cotation
    price: Decimal  # cours à la date du rapport, devise de cotation
    value: Decimal  # CHF
    weight_pct: Decimal


class PortfolioReport(_Frozen):
    number: str
    name: str
    strategy: str
    deposits_year: Decimal  # versements de l'année (affichés par VIAC, pas utilisés)
    balance: Decimal  # solde du portefeuille, CHF
    cash: Decimal | None  # « Compte 3a » des liquidités, CHF
    positions: list[Position]


class Report(_Frozen):
    """« Rapport au JJ.MM.AAAA » (Créer un rapport)."""

    on_date: str
    generated_on: str | None
    portfolios: list[PortfolioReport]


class Ignored(_Frozen):
    """Document reconnu qui n'écrit rien (attestation fiscale, relevé récapitulatif)."""

    document: Literal["attestation", "statement"]
