"""Fichier `hub.market.v1` du collecteur « market » (lot 6) : lecture et contrôle des listes
(cours de change, cours, soldes, transactions, opérations), sans rien écrire."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from hub.domains.finance.patrimoine.model import instruments
from hub.domains.finance.patrimoine.model.instruments import AssetError, DocumentError
from hub.domains.finance.sources.infra import operations

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
class Transaction:
    account: str  # référence externe : crypto:<nom>
    key: str
    symbol: str
    on_date: str
    txid: str
    quantity: Decimal  # net : positif reçu, négatif envoyé (frais compris)
    fee: Decimal  # frais payés par le portefeuille, positifs


@dataclass(frozen=True)
class MarketFile:
    fetched_on: str
    fx: list[Fx] = field(default_factory=list)
    prices: list[Price] = field(default_factory=list)
    balances: list[Balance] = field(default_factory=list)
    transactions: list[Transaction] = field(default_factory=list)
    operations: list[operations.Operation] = field(default_factory=list)

    @property
    def on_date(self) -> str:
        dates = [x.on_date for x in self.fx] + [x.on_date for x in self.prices]
        return min(dates, default=self.fetched_on)

    def rows(self) -> list[tuple[int, str | None, str | None]]:
        out: list[tuple[int, str | None, str | None]] = [(0, self.on_date, self.fetched_on)]
        out += [(i + 1, None, b.on_date) for i, b in enumerate(self.balances)]
        first = len(self.balances) + 1
        out += [(first + i, None, t.on_date) for i, t in enumerate(self.transactions)]
        first += len(self.transactions)
        out += [(first + i, None, o.on_date) for i, o in enumerate(self.operations)]
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
        return instruments.number(value)
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
        return instruments.instrument_key(str(item.get("instrument") or ""), kind), kind
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
    txs = []
    for x in doc.get("transactions") or []:
        if not isinstance(x, dict):
            continue
        account = str(x.get("account") or "")
        txid = str(x.get("txid") or "")
        if not re.match(r"^crypto:[a-z0-9][a-z0-9-]{0,40}$", account):
            raise MarketError("portefeuille illisible")
        if not re.match(r"^[A-Za-z0-9]{1,128}$", txid):
            raise MarketError("transaction illisible")
        key, _kind = _key({**x, "kind": "crypto"})
        fee = _dec(x.get("fee") or "0")
        if fee < 0:
            raise MarketError("frais négatifs")
        txs.append(
            Transaction(
                account,
                key,
                instruments.symbol_of(key),
                _iso(x.get("on_date")),
                txid,
                _dec(x.get("quantity")),
                fee,
            )
        )
    txs.sort(key=lambda t: (t.on_date, t.txid))
    try:
        ops = operations.parse(doc.get("operations") or [], _dec, _iso)
    except operations.ExchangeError as exc:
        raise MarketError(str(exc)) from None
    return MarketFile(_iso(doc.get("fetched_at")), fx, prices, balances, txs, ops)
