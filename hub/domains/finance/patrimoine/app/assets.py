"""Instruments, cours et relevés de positions communs aux sources du lot 6 (IBKR, cours du
marché, portefeuilles crypto, positions saisies à la main), dans la transaction de l'appelant.

Clé d'un instrument (`instruments.isin`) : l'ISIN quand il existe, sinon une clé typée,
`CRYPTO:BTC` pour une crypto, `IBKR:<conid>` pour un titre IBKR sans ISIN, `SYM:<symbole>` pour
une position saisie à la main. `prices` et `holdings` sont en ajout seul et chaînés au journal :
une ligne déjà présente (même instrument, même date, même source) n'est jamais réécrite.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import Connection, text

from hub.domains.finance.patrimoine.model.instruments import (
    CRYPTO_NAMES,
    KINDS,
    price_text,
    qty_text,
    symbol_of,
)
from hub.domains.finance.registre.app import catalog, ledger
from hub.kernel.clock import now_iso
from hub.kernel.money import Money


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


def price_at(conn: Connection, key: str, on_date: str) -> tuple[Decimal, str] | None:
    """Dernier cours connu d'un instrument à cette date : (cours, devise)."""
    row = conn.execute(
        text(
            "SELECT price, currency FROM prices WHERE isin = :i AND on_date <= :d "
            "ORDER BY on_date DESC, source DESC LIMIT 1"
        ),
        {"i": key, "d": on_date},
    ).first()
    return (Decimal(row[0]), str(row[1])) if row else None


def positions_account(conn: Connection, ref: str) -> catalog.Account | None:
    return catalog.account_by_ref(conn, ref)


def opening_date(conn: Connection, account_id: str) -> str | None:
    row = conn.execute(
        text("SELECT booking_date FROM entries WHERE account_id = :a AND kind = 'opening'"),
        {"a": account_id},
    ).first()
    return str(row[0]) if row else None
