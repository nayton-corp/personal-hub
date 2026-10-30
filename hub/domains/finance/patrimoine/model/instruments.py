"""Instruments (lot 6), sans base : la clé d'un instrument (ISIN, `CRYPTO:BTC`, `IBKR:<conid>`,
`SYM:<symbole>`), les nombres des documents en `Decimal`, et les refus d'un document."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation, localcontext

from hub.kernel.money import CURRENCY_EXPONENTS, DECIMAL_CONTEXT

ISIN = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}\d$")
_SYMBOL = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,19}$")
KINDS = ("fund", "etf", "stock", "bond", "crypto", "other")
PRICE_PLACES = 10
# noms des cryptos courantes, pour l'affichage
CRYPTO_NAMES = {
    "BTC": "Bitcoin",
    "ETH": "Ethereum",
    "SOL": "Solana",
    "ADA": "Cardano",
    "DOT": "Polkadot",
    "XRP": "XRP",
    "LTC": "Litecoin",
    "USDC": "USD Coin",
    "USDT": "Tether",
}


class AssetError(ValueError):
    pass


class DocumentError(ValueError):
    """Fichier refusé ; `code` est un type d'erreur stable de l'API (`import.invalid_schema`)."""

    def __init__(self, reason: str, code: str = "import.invalid_schema") -> None:
        super().__init__(reason)
        self.code = code
        self.reason = reason


def number(value: object) -> Decimal:
    """Décimal exact depuis un texte (« 1'234.50 », « 1,234.50 » refusé s'il est ambigu)."""
    raw = str(value).replace("'", "").replace("’", "").replace(" ", "").strip()
    if raw.count(",") and raw.count("."):
        raw = raw.replace(",", "")  # 1,234.50 : séparateur de milliers
    elif raw.count(",") == 1:
        raw = raw.replace(",", ".")  # 12,5 : virgule décimale
    try:
        with localcontext(DECIMAL_CONTEXT):
            out = Decimal(raw)
    except InvalidOperation:
        raise AssetError("nombre illisible") from None
    if not out.is_finite():
        raise AssetError("nombre illisible")
    return out


def qty_text(value: Decimal) -> str:
    """Quantité exacte, sans exposant ni zéros superflus : '12.345', '-2', '0'."""
    out = format(value.normalize(), "f")
    return "0" if out in ("-0", "") else out


def price_text(value: Decimal) -> str:
    with localcontext(DECIMAL_CONTEXT):
        return qty_text(value.quantize(Decimal(1).scaleb(-PRICE_PLACES)))


def known_currency(code: str) -> bool:
    return code in CURRENCY_EXPONENTS


def crypto_key(symbol: str) -> str:
    return f"CRYPTO:{symbol.upper()}"


def instrument_key(identifier: str, kind: str | None = None) -> str:
    """ISIN tel quel ; sinon `CRYPTO:<symbole>` pour une crypto, `SYM:<symbole>` sinon. Une clé
    déjà typée (`CRYPTO:`, `IBKR:`, `SYM:`) est gardée."""
    value = identifier.strip().upper()
    if ISIN.match(value) or re.match(r"^(CRYPTO|IBKR|SYM):[A-Z0-9.\-]{1,30}$", value):
        return value
    if not _SYMBOL.match(value):
        raise AssetError("identifiant d'instrument illisible")
    return crypto_key(value) if kind == "crypto" else f"SYM:{value}"


def symbol_of(key: str) -> str:
    return key.split(":", 1)[1] if ":" in key else key


@dataclass
class Result:
    """Résultat de l'application d'un relevé d'un document du lot 6."""

    status: str = "applied"  # 'applied' | 'needs_review'
    reasons: set[str] = field(default_factory=set)
    new: int = 0
    duplicates: int = 0
    account_id: str | None = None

    def review(self, reason: str) -> Result:
        self.status = "needs_review"
        self.reasons.add(reason)
        return self
