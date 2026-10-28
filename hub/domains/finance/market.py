"""Cours du marché et soldes des portefeuilles crypto (lot 6) : fichier `hub.market.v1` déposé
par le collecteur « market ».

Le fichier porte trois listes, chacune facultative :

- `fx` : cours de change de la BCE (1 devise = rate dans la devise de base), vers `fx_rates` ;
- `prices` : cours quotidiens (cryptos, titres cotés), vers `prices` ;
- `balances` : solde d'un portefeuille crypto relevé sur la chaîne (adresses publiques), qui
  devient un relevé de positions du compte `crypto:<nom>` à cette date ;
- `transactions` : une transaction du portefeuille sur la chaîne (net reçu ou envoyé, frais
  payés), qui devient une opération au registre du compte, en devise de base, et un mouvement
  de parts. Une arrivée appariée à un retrait d'une plateforme (même quantité, même crypto,
  au plus 5 jours avant) prend la valeur du retrait : c'est un virement entre mes comptes.

Relevé 0 : les cours ; puis un relevé par portefeuille, puis un par transaction. Un
portefeuille dont le compte n'est pas encore déclaré (`hub finance crypto add-wallet`) attend,
le reste s'applique.
Montants et cours sont des textes décimaux : jamais de flottant.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal, localcontext
from typing import Any

from sqlalchemy import Connection, text

from hub.core import canonical
from hub.core.ids import urn
from hub.core.money import DECIMAL_CONTEXT, base_currency
from hub.domains.finance import assets, catalog, institutions, ledger
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

    @property
    def on_date(self) -> str:
        dates = [x.on_date for x in self.fx] + [x.on_date for x in self.prices]
        return min(dates, default=self.fetched_on)

    def rows(self) -> list[tuple[int, str | None, str | None]]:
        out: list[tuple[int, str | None, str | None]] = [(0, self.on_date, self.fetched_on)]
        out += [(i + 1, None, b.on_date) for i, b in enumerate(self.balances)]
        first = len(self.balances) + 1
        out += [(first + i, None, t.on_date) for i, t in enumerate(self.transactions)]
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
                assets.symbol_of(key),
                _iso(x.get("on_date")),
                txid,
                _dec(x.get("quantity")),
                fee,
            )
        )
    txs.sort(key=lambda t: (t.on_date, t.txid))
    return MarketFile(_iso(doc.get("fetched_at")), fx, prices, balances, txs)


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
    if account.kind != "crypto" or account.currency != base_currency():
        return result.review("currency_mismatch")
    known = price_at(conn, b.key, b.on_date)
    with localcontext(DECIMAL_CONTEXT):
        value, ccy = (b.quantity * known[0], known[1]) if known else (Decimal(0), account.currency)
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


WINDOW_DAYS = 5  # un retrait de plateforme arrive sur le portefeuille dans ce délai


def _peer(conn: Connection, t: Transaction) -> tuple[int, int] | None:
    """Le retrait d'un autre compte de la même quantité de la même crypto, au plus
    WINDOW_DAYS jours avant l'arrivée, pas encore apparié : (seq, montant)."""
    start = (date.fromisoformat(t.on_date) - timedelta(days=WINDOW_DAYS)).isoformat()
    codes = institutions.like_any("e.bank_tx_code", institutions.prefixes(transfer=True))
    rows = conn.execute(
        text(
            "SELECT e.seq, e.amount_minor, json_extract(e.fx_json, '$.quantity') "  # noqa: S608 - codes déclarés
            "FROM entries e JOIN accounts a ON a.id = e.account_id "
            f"WHERE ({codes}) AND e.amount_minor < 0 AND a.external_ref != :acc "
            "AND e.booking_date BETWEEN :s AND :d "
            "AND json_extract(e.fx_json, '$.currency') = :c "
            "AND NOT EXISTS (SELECT 1 FROM entries x WHERE x.bank_tx_code LIKE 'CRYPTO/%' "
            "  AND json_extract(x.fx_json, '$.peer') = e.seq) "
            "ORDER BY e.booking_date DESC, e.seq"
        ),
        {"acc": t.account, "s": start, "d": t.on_date, "c": t.symbol},
    ).fetchall()
    for seq, amount, qty in rows:
        try:
            if qty is not None and -Decimal(str(qty)) == t.quantity:
                return int(seq), int(amount)
        except ArithmeticError:
            continue
    return None


class _Chain:
    """Écritures des transactions d'un fichier : un écrivain, le change, les comptes ouverts."""

    def __init__(self, conn: Connection, import_id: str) -> None:
        from hub.domains.finance import ibkr, valuation  # import circulaire (documents)

        self.conn = conn
        self.import_id = import_id
        self.fx = valuation.FxTable(conn)
        self.writer = ibkr.Writer(conn, import_id, "chain", Result(), namespace="chain")
        self.opened: set[str] = set()

    def value(self, t: Transaction, quantity: Decimal) -> int | None:
        known = price_at(self.conn, t.key, t.on_date)
        if known is None:
            return None
        with localcontext(DECIMAL_CONTEXT):
            return self.fx.convert(quantity * known[0], known[1], t.on_date)

    def open(self, account: catalog.Account, first: str) -> None:
        if account.id in self.opened:
            return
        self.opened.add(account.id)
        if self.conn.execute(
            text("SELECT 1 FROM entries WHERE account_id = :a LIMIT 1"), {"a": account.id}
        ).first():
            return
        from hub.domains.finance.importer import open_account  # import circulaire

        day = (date.fromisoformat(first) - timedelta(days=1)).isoformat()
        open_account(self.conn, account.id, day, 0, account.currency)

    def apply(self, t: Transaction, first: str) -> Result:
        result = Result()
        account = catalog.account_by_ref(self.conn, t.account)
        if account is None:
            return result.review("unknown_account")
        result.account_id = account.id
        if account.kind != "crypto" or account.currency != base_currency():
            return result.review("currency_mismatch")
        self.open(account, first)
        self.writer.result = result
        detail = {"txid": t.txid, "currency": t.symbol}
        sent = t.quantity + t.fee  # hors frais : ce qui quitte le portefeuille (négatif)
        if t.quantity > 0:
            peer = _peer(self.conn, t)
            amount = -peer[1] if peer else self.value(t, t.quantity)
            legs = [("receive", "CRYPTO/RECEIVE", f"Réception {t.symbol}", t.quantity, amount)]
            if peer:
                detail["peer"] = str(peer[0])
            cost = amount
        else:
            fee = self.value(t, -t.fee) if t.fee else 0
            legs = [
                ("send", "CRYPTO/SEND", f"Envoi {t.symbol}", sent, self.value(t, sent)),
                ("fee", "CRYPTO/FEE", f"Frais de réseau {t.symbol}", -t.fee, fee),
            ]
            cost = self.value(t, t.quantity)
        if cost is None or any(v is None for *_x, v in legs):
            return result.review("missing_price")
        for leg, code, label, qty, amount in legs:
            if amount:
                fx = canonical.dumps({**detail, "quantity": assets.qty_text(qty)})
                self.writer.entry(
                    account,
                    f"{t.txid}|{leg}",
                    t.on_date,
                    int(amount),
                    code,
                    label,
                    remittance=f"{assets.qty_text(qty)} {t.symbol}",
                    fx_json=fx,
                )
        trade_key = ledger.dedup_hash(f"chain|{t.account}|{t.txid}|trade")
        if (
            t.quantity
            and not self.conn.execute(
                text("SELECT 1 FROM trades WHERE dedup_key = :k"), {"k": trade_key}
            ).first()
        ):
            assets.upsert_instrument(
                self.conn, t.key, None, kind="crypto", symbol=assets.symbol_of(t.key)
            )
            ledger.append(
                self.conn,
                "trades",
                {
                    "account_id": account.id,
                    "trade_date": t.on_date,
                    "isin": t.key,
                    "quantity": assets.qty_text(t.quantity),
                    "amount_minor": int(cost),
                    "currency": account.currency,
                    "dedup_key": trade_key,
                    "import_id": self.import_id,
                    "created_at": self.writer.created,
                },
            )
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
    if doc.transactions:
        chain = _Chain(conn, import_id)
        firsts: dict[str, str] = {}
        for t in doc.transactions:
            firsts.setdefault(t.account, t.on_date)
        for i, t in enumerate(doc.transactions, start=len(doc.balances) + 1):
            if indexes is None or i in indexes:
                out.append((i, chain.apply(t, firsts[t.account])))
        for account_id, count in sorted(chain.writer.touched.items()):
            ledger.append_event(
                conn,
                "entries.appended",
                urn("finance", "account", account_id),
                {"import_id": import_id, "count": count},
            )
    return out
