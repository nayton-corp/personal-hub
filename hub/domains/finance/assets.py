"""Instruments, cours et relevés de positions communs aux sources du lot 6 (IBKR, cours du
marché, portefeuilles crypto, positions saisies à la main), dans la transaction de l'appelant.

Clé d'un instrument (`instruments.isin`) : l'ISIN quand il existe, sinon une clé typée,
`CRYPTO:BTC` pour une crypto, `IBKR:<conid>` pour un titre IBKR sans ISIN, `SYM:<symbole>` pour
une position saisie à la main. `prices` et `holdings` sont en ajout seul et chaînés au journal :
une ligne déjà présente (même instrument, même date, même source) n'est jamais réécrite.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation, localcontext

from sqlalchemy import Connection, text

from hub.core.clock import now_iso
from hub.core.money import CURRENCY_EXPONENTS, DECIMAL_CONTEXT, Money
from hub.domains.finance import catalog, ledger

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


def upsert_instrument(
    conn: Connection,
    key: str,
    name: str | None,
    *,
    kind: str = "other",
    currency: str | None = None,
    symbol: str | None = None,
    asset_class: str | None = None,
    sub_class: str | None = None,
) -> None:
    """Crée l'instrument, ou complète ce qui lui manque ; un nom déjà connu n'est pas remplacé
    (le rapport VIAC, plus complet, reste la référence de ses fonds)."""
    if kind not in KINDS:
        kind = "other"
    if not name:
        name = CRYPTO_NAMES.get(symbol_of(key), symbol_of(key)) if kind == "crypto" else key
    found = conn.execute(text("SELECT 1 FROM instruments WHERE isin = :i"), {"i": key}).first()
    params = {
        "i": key,
        "n": name[:120],
        "k": kind,
        "c": currency,
        "s": symbol,
        "a": asset_class,
        "sc": sub_class,
        "at": now_iso(),
    }
    if found is None:
        conn.execute(
            text(
                "INSERT INTO instruments (isin, name, asset_class, sub_class, currency, kind, "
                "symbol, updated_at) VALUES (:i, :n, :a, :sc, :c, :k, :s, :at)"
            ),
            params,
        )
    else:
        conn.execute(
            text(
                "UPDATE instruments SET currency = coalesce(currency, :c), "
                "symbol = coalesce(symbol, :s), asset_class = coalesce(asset_class, :a), "
                "sub_class = coalesce(sub_class, :sc), "
                "kind = CASE WHEN kind = 'other' OR (kind = 'fund' AND :k != 'other') THEN :k "
                "ELSE kind END WHERE isin = :i"
            ),
            params,
        )


def add_price(
    conn: Connection,
    key: str,
    on_date: str,
    price: Decimal,
    currency: str,
    source: str,
    import_id: str | None,
) -> bool:
    """Un cours de plus ; False s'il est déjà connu pour cette date et cette source."""
    found = conn.execute(
        text("SELECT 1 FROM prices WHERE isin = :i AND on_date = :d AND source = :s"),
        {"i": key, "d": on_date, "s": source},
    ).first()
    if found is not None:
        return False
    ledger.append(
        conn,
        "prices",
        {
            "isin": key,
            "on_date": on_date,
            "price": price_text(price),
            "currency": currency,
            "source": source,
            "import_id": import_id,
            "created_at": now_iso(),
        },
    )
    return True


def add_holding(
    conn: Connection,
    account_id: str,
    on_date: str,
    key: str,
    quantity: Decimal,
    value: Decimal,
    currency: str,
    import_id: str,
    cost_price: Decimal | None = None,
) -> bool:
    found = conn.execute(
        text("SELECT 1 FROM holdings WHERE account_id = :a AND on_date = :d AND isin = :i"),
        {"a": account_id, "d": on_date, "i": key},
    ).first()
    if found is not None:
        return False
    ledger.append(
        conn,
        "holdings",
        {
            "account_id": account_id,
            "on_date": on_date,
            "isin": key,
            "quantity": qty_text(quantity),
            "value_minor": Money.from_decimal(value, currency).minor,
            "currency": currency,
            "cost_price": price_text(cost_price) if cost_price is not None else None,
            "import_id": import_id,
            "created_at": now_iso(),
        },
    )
    return True


def add_fx(
    conn: Connection, on_date: str, base: str, quote: str, rate: Decimal, source: str
) -> bool:
    """Cours de change (1 base = rate quote) ; jamais réécrit."""
    if base == quote or rate <= 0:
        return False
    result = conn.execute(
        text(
            "INSERT INTO fx_rates (on_date, base, quote, rate, source) VALUES (:d, :b, :q, :r, :s) "
            "ON CONFLICT DO NOTHING"
        ),
        {"d": on_date, "b": base, "q": quote, "r": price_text(rate), "s": source},
    )
    return bool(result.rowcount)


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


def positions_account(conn: Connection, ref: str) -> catalog.Account | None:
    return catalog.account_by_ref(conn, ref)


def opening_date(conn: Connection, account_id: str) -> str | None:
    row = conn.execute(
        text("SELECT booking_date FROM entries WHERE account_id = :a AND kind = 'opening'"),
        {"a": account_id},
    ).first()
    return str(row[0]) if row else None
