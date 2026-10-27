"""Cours du marché et soldes des portefeuilles crypto (lot 6) : fichier `hub.market.v1` déposé
par le collecteur « market ».

Le fichier porte trois listes, chacune facultative :

- `fx` : cours de change de la BCE (1 devise = rate CHF), vers `fx_rates` ;
- `prices` : cours quotidiens (cryptos, titres cotés), vers `prices` ;
- `balances` : solde d'un portefeuille crypto relevé sur la chaîne (adresses publiques), qui
  devient un relevé de positions du compte `crypto:<nom>` à cette date.

Relevé 0 : les cours ; relevé 1 et suivants : un par portefeuille. Un portefeuille dont le
compte n'est pas encore déclaré (`hub finance crypto add-wallet`) attend, le reste s'applique.
Montants et cours sont des textes décimaux : jamais de flottant.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, localcontext
from typing import Any

from sqlalchemy import Connection, text

from hub.core.ids import urn
from hub.core.money import DECIMAL_CONTEXT
from hub.domains.finance import assets, catalog, ledger
from hub.domains.finance.assets import AssetError, DocumentError, Result

FORMAT = "hub.market.v1"
SOURCE = "market"
MAX_BYTES = 20 * 1024 * 1024
_SOURCE_NAME = re.compile(r"^[a-z0-9_]{2,20}$")
_CCY = re.compile(r"^[A-Z]{3}$")


class MarketError(DocumentError):
    pass


@dataclass(frozen=True)
class Fx:
    on_date: str
    base: str
    quote: str
    rate: Decimal
    source: str


@dataclass(frozen=True)
class Price:
    key: str
    on_date: str
    price: Decimal
    currency: str
    source: str
    name: str | None
    kind: str


@dataclass(frozen=True)
class Balance:
    account: str  # référence externe : crypto:<nom>
    key: str
    on_date: str
    quantity: Decimal


@dataclass(frozen=True)
class MarketFile:
    fetched_on: str
    fx: list[Fx] = field(default_factory=list)
    prices: list[Price] = field(default_factory=list)
    balances: list[Balance] = field(default_factory=list)

    @property
    def on_date(self) -> str:
        dates = [x.on_date for x in self.fx] + [x.on_date for x in self.prices]
        return min(dates, default=self.fetched_on)

    def rows(self) -> list[tuple[int, str | None, str | None]]:
        out: list[tuple[int, str | None, str | None]] = [(0, self.on_date, self.fetched_on)]
        out += [(i + 1, None, b.on_date) for i, b in enumerate(self.balances)]
        return out


def is_market(data: bytes) -> bool:
    if data.lstrip()[:1] != b"{":
        return False
    try:
        doc = json.loads(data, parse_float=str)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    return isinstance(doc, dict) and doc.get("format") == FORMAT


def _iso(value: Any) -> str:
    try:
        return date.fromisoformat(str(value)[:10]).isoformat()
    except ValueError:
        raise MarketError("date illisible") from None


def _dec(value: Any) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise MarketError("nombre illisible")
    try:
        return assets.number(value)
    except AssetError:
        raise MarketError("nombre illisible") from None


def _src(value: Any) -> str:
    s = str(value or "")
    if not _SOURCE_NAME.match(s):
        raise MarketError("source de cours illisible")
    return s


def _ccy(value: Any) -> str:
    s = str(value or "").upper()
    if not _CCY.match(s):
        raise MarketError("devise illisible")
    return s


def _key(item: dict[str, Any]) -> tuple[str, str]:
    kind = str(item.get("kind") or "other")
    try:
        return assets.instrument_key(str(item.get("instrument") or ""), kind), kind
    except AssetError:
        raise MarketError("instrument illisible") from None


def parse(data: bytes) -> MarketFile:
    if len(data) > MAX_BYTES:
        raise MarketError("fichier trop volumineux")
    try:
        doc = json.loads(data, parse_float=str, parse_int=str)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise MarketError("JSON illisible") from None
    if not isinstance(doc, dict) or doc.get("format") != FORMAT:
        raise MarketError("pas un fichier de cours du collecteur")
    fx = [
        Fx(
            _iso(x.get("on_date")),
            _ccy(x.get("base")),
            _ccy(x.get("quote")),
            _dec(x.get("rate")),
            _src(x.get("source")),
        )
        for x in doc.get("fx") or []
        if isinstance(x, dict)
    ]
    prices = []
    for x in doc.get("prices") or []:
        if not isinstance(x, dict):
            continue
        key, kind = _key(x)
        name = x.get("name")
        prices.append(
            Price(
                key,
                _iso(x.get("on_date")),
                _dec(x.get("price")),
                _ccy(x.get("currency")),
                _src(x.get("source")),
                str(name)[:120] if name else None,
                kind,
            )
        )
    balances = []
    for x in doc.get("balances") or []:
        if not isinstance(x, dict):
            continue
        account = str(x.get("account") or "")
        if not re.match(r"^crypto:[a-z0-9][a-z0-9-]{0,40}$", account):
            raise MarketError("portefeuille illisible")
        key, _kind = _key({**x, "kind": "crypto"})
        balances.append(Balance(account, key, _iso(x.get("on_date")), _dec(x.get("quantity"))))
    return MarketFile(_iso(doc.get("fetched_at")), fx, prices, balances)


def _apply_rates(conn: Connection, import_id: str, doc: MarketFile) -> Result:
    result = Result()
    for f in doc.fx:
        if not (assets.known_currency(f.base) and assets.known_currency(f.quote)):
            continue
        if assets.add_fx(conn, f.on_date, f.base, f.quote, f.rate, f.source):
            result.new += 1
        else:
            result.duplicates += 1
    for p in doc.prices:
        if not assets.known_currency(p.currency) or p.price <= 0:
            result.reasons.add("unknown_currency")
            continue
        assets.upsert_instrument(
            conn, p.key, p.name, kind=p.kind, currency=p.currency, symbol=assets.symbol_of(p.key)
        )
        if assets.add_price(conn, p.key, p.on_date, p.price, p.currency, p.source, import_id):
            result.new += 1
        else:
            result.duplicates += 1
    return result


def price_at(conn: Connection, key: str, on_date: str) -> tuple[Decimal, str] | None:
    row = conn.execute(
        text(
            "SELECT price, currency FROM prices WHERE isin = :i AND on_date <= :d "
            "ORDER BY on_date DESC, source DESC LIMIT 1"
        ),
        {"i": key, "d": on_date},
    ).first()
    return (Decimal(row[0]), str(row[1])) if row else None


def apply_balance(conn: Connection, import_id: str, b: Balance) -> Result:
    result = Result()
    account = catalog.account_by_ref(conn, b.account)
    if account is None:
        return result.review("unknown_account")
    result.account_id = account.id
    if account.kind != "crypto" or account.currency != "CHF":
        return result.review("currency_mismatch")
    known = price_at(conn, b.key, b.on_date)
    with localcontext(DECIMAL_CONTEXT):
        value, ccy = (b.quantity * known[0], known[1]) if known else (Decimal(0), "CHF")
    if known is None:
        result.reasons.add("missing_price")  # observation : la valeur suivra le premier cours
    assets.upsert_instrument(conn, b.key, None, kind="crypto", symbol=assets.symbol_of(b.key))
    if assets.add_holding(conn, account.id, b.on_date, b.key, b.quantity, value, ccy, import_id):
        result.new += 1
        ledger.append_event(
            conn,
            "holdings.recorded",
            urn("finance", "account", account.id),
            {"import_id": import_id, "count": 1},
        )
    else:
        result.duplicates += 1
    return result


def apply(
    conn: Connection, import_id: str, doc: MarketFile, indexes: set[int] | None
) -> list[tuple[int, Result]]:
    out = []
    if indexes is None or 0 in indexes:
        out.append((0, _apply_rates(conn, import_id, doc)))
    for i, b in enumerate(doc.balances, start=1):
        if indexes is None or i in indexes:
            out.append((i, apply_balance(conn, import_id, b)))
    return out
