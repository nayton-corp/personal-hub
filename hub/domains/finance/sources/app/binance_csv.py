"""Export « Trade History » de Binance (CSV) : les ordres exécutés que l'API ne sert plus (paire
retirée de la cote comme BUSD, ou échange ancien que `myTrades` ne rend plus), au registre du
compte `crypto:binance` exactement comme les opérations du collecteur (`exchange`), avec leurs
mouvements de parts (audit M15).

Deux en-têtes : l'ancien `Date(UTC),Pair,Side,Price,Executed,Amount,Fee` (une ligne = une
exécution, identifiant tiré du contenu) et l'export « Historique des trades Spot » en français
(`N° de commande,Durée,Paire,Côté,…`), dont les exécutions d'un même ordre sont regroupées en
une opération, comme le fait le collecteur. `Executed`, `Amount` et `Fee` portent leur actif
collé au nombre (`0.0012BTC`).

Un ordre que le registre a déjà (lu par l'API : même jour à un jour près, même actif acheté ou
vendu, même quantité) n'est pas repris : l'export entier peut être déposé sans doublon.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation, localcontext
from typing import Any

from sqlalchemy import Connection, text

from hub.domains.finance.patrimoine.model import instruments
from hub.domains.finance.patrimoine.model.instruments import DocumentError, Result
from hub.domains.finance.sources.app import exchange, market
from hub.domains.finance.sources.infra.operations import STABLE, Leg, Operation
from hub.kernel.money import DECIMAL_CONTEXT

SOURCE = "binance_csv"
ACCOUNT = "crypto:binance"
HEADER = ("Date(UTC)", "Pair", "Side", "Price", "Executed", "Amount", "Fee")
# export « Historique des trades Spot » (site en français) ; les colonnes AOR suivent parfois
HEADER_FR = ("N° de commande", "Durée", "Paire", "Côté", "Prix", "Exécuté", "Montant", "Frais")
_KEYS = ("date", "pair", "side", "price", "executed", "amount", "fee")
COLUMNS = {
    HEADER: dict(zip(_KEYS, HEADER, strict=True)),
    HEADER_FR: dict(zip(("order", *_KEYS), HEADER_FR, strict=True)),
}
MAX_BYTES = 20 * 1024 * 1024
_QTY = re.compile(r"^([0-9]*\.?[0-9]+)([A-Z0-9]{2,20})$")
_WHEN = re.compile(r"^(\d{4}-\d{2}-\d{2}) (\d{2}):(\d{2}):(\d{2})$")


class BinanceCsvError(DocumentError):
    pass


@dataclass(frozen=True)
class Statement:
    operations: list[Operation]

    @property
    def on_date(self) -> str:
        return min((o.on_date for o in self.operations), default="1900-01-01")

    def rows(self) -> list[tuple[int, str | None, str | None]]:
        return [(i, None, o.on_date) for i, o in enumerate(self.operations)]


def _text(data: bytes) -> str | None:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None


def detect(name: str, data: bytes) -> str | None:
    if len(data) > MAX_BYTES or not name.lower().endswith(".csv"):
        return None
    text = _text(data[:4096])
    if text is None:
        return None
    first = next((line for line in text.splitlines() if line.strip()), "")
    return SOURCE if _header(c.strip() for c in first.split(",")) else None


def _header(names: Any) -> tuple[str, ...] | None:
    got = tuple(names)
    for header in COLUMNS:
        if got[: len(header)] == header:
            return header
    return None


def _split(value: str, what: str) -> tuple[Decimal, str]:
    m = _QTY.match(value.replace(",", "").strip())
    if not m:
        raise BinanceCsvError(f"{what} illisible : {value!r}")
    try:
        qty = Decimal(m.group(1))
    except InvalidOperation:
        raise BinanceCsvError(f"{what} illisible : {value!r}") from None
    return qty, m.group(2)


def _plain(q: Decimal) -> str:
    return format(q.normalize(), "f")


def _fee_leg(fee: Decimal, asset: str, base: str, quote: str, price: Decimal) -> Leg:
    """Les frais : dans la monnaie de cotation, ou dans l'actif acheté au prix de l'ordre (en
    dollar pour un stablecoin) ; en BNB, sans contre-valeur ici, ils attendent un cours."""
    if asset in (quote, base):
        with localcontext(DECIMAL_CONTEXT):
            worth = fee if asset == quote else fee * price
        if quote in STABLE:
            return Leg(asset, -fee, "fee", worth, "USD")
        if instruments.known_currency(quote):
            return Leg(asset, -fee, "fee", worth, quote)
    return Leg(asset, -fee, "fee")


@dataclass
class _Order:
    """Une opération en construction : une exécution, ou toutes celles d'un ordre."""

    key: str
    on: str
    pair: str
    base: str
    quote: str
    sign: int
    price: Decimal
    executed: Decimal = Decimal(0)
    amount: Decimal = Decimal(0)
    fees: dict[str, Decimal] = field(default_factory=dict)

    def operation(self) -> Operation:
        legs = [
            Leg(self.base, self.sign * self.executed, "trade"),
            Leg(self.quote, -self.sign * self.amount, "trade"),
        ]
        for asset, fee in sorted(self.fees.items()):
            if fee:
                legs.append(_fee_leg(fee, asset, self.base, self.quote, self.price))
        return Operation(ACCOUNT, self.key, "trade", self.on, tuple(legs))


def parse(data: bytes) -> Statement:
    if len(data) > MAX_BYTES:
        raise BinanceCsvError("fichier trop volumineux")
    text_ = _text(data)
    if text_ is None:
        raise BinanceCsvError("texte illisible")
    reader = csv.DictReader(io.StringIO(text_))
    header = _header(c.strip() for c in reader.fieldnames or ())
    if header is None:
        raise BinanceCsvError("pas un export « Trade History » de Binance")
    col = COLUMNS[header]
    seen: dict[str, int] = {}
    orders: dict[str, _Order] = {}
    for raw in reader:
        row = {(k or "").strip(): v for k, v in raw.items()}
        if not any((v or "").strip() for v in row.values() if isinstance(v, str)):
            continue
        when = _WHEN.match((row[col["date"]] or "").strip())
        if not when:
            raise BinanceCsvError("date illisible")
        pair, side = (
            (row[col["pair"]] or "").strip().upper(),
            (row[col["side"]] or "").strip().upper(),
        )
        if side not in ("BUY", "SELL"):
            raise BinanceCsvError(f"sens illisible : {side!r}")
        executed, base = _split(row[col["executed"]] or "", "quantité")
        amount, quote = _split(row[col["amount"]] or "", "montant")
        fee, fee_asset = _split(row[col["fee"]] or "0" + quote, "frais")
        try:
            price = Decimal((row[col["price"]] or "0").replace(",", "").strip())
        except InvalidOperation:
            raise BinanceCsvError("prix illisible") from None
        if pair != base + quote:
            raise BinanceCsvError(f"paire {pair} et actifs {base}/{quote} en désaccord")
        sign = 1 if side == "BUY" else -1
        number = (row.get(col.get("order", ""), "") or "").strip()
        if "order" in col:
            if not number.isdigit():
                raise BinanceCsvError(f"numéro de commande illisible : {number!r}")
            key = f"csv:{pair}:order:{number}"
        else:
            stamp = f"{when.group(1)}T{when.group(2)}{when.group(3)}{when.group(4)}"
            base_key = f"csv:{pair}:{stamp}:{side}:{_plain(executed)}:{_plain(amount)}"
            n = seen.get(base_key, 0)
            seen[base_key] = n + 1
            key = f"{base_key}:{n}"
        order = orders.get(key)
        if order is None:
            order = orders[key] = _Order(
                key, when.group(1), pair, base, quote, sign, price, fees={}
            )
        elif order.sign != sign:
            raise BinanceCsvError(f"ordre {number} à la fois acheté et vendu")
        order.on = min(order.on, when.group(1))
        order.executed += executed
        order.amount += amount
        order.fees[fee_asset] = order.fees.get(fee_asset, Decimal(0)) + fee
    if not orders:
        raise BinanceCsvError("export vide")
    out = sorted((o.operation() for o in orders.values()), key=lambda o: (o.on_date, o.id))
    return Statement(out)


def known(conn: Connection, op: Operation) -> bool:
    """L'ordre est déjà au registre sous une autre clé (lu par l'API) : une jambe d'échange du
    même actif, de la même quantité signée, sur le même compte, à un jour près (l'export peut
    dater en heure locale, l'API en UTC)."""
    leg = op.legs[0]
    found = conn.execute(
        text(
            "SELECT m.quantity FROM crypto_moves m JOIN entries e ON e.seq = m.entry_seq "
            "JOIN accounts a ON a.id = e.account_id WHERE a.external_ref = :ref "
            "AND m.role = 'trade' AND m.asset = :asset "
            "AND e.booking_date BETWEEN date(:on, '-1 day') AND date(:on, '+1 day')"
        ),
        {"ref": op.account, "asset": leg.symbol.upper(), "on": op.on_date},
    ).all()
    return any(_same(r[0], leg.quantity) for r in found)


def _same(stored: str, quantity: Decimal) -> bool:
    try:
        return Decimal(stored) == quantity
    except InvalidOperation:
        return False


def apply(
    conn: Connection, import_id: str, doc: Statement, indexes: set[int] | None
) -> list[tuple[int, Result]]:
    journal = exchange.Journal(conn, import_id)
    first = doc.on_date
    out: list[tuple[int, Any]] = []
    chosen = [(i, o) for i, o in enumerate(doc.operations) if indexes is None or i in indexes]
    # regardé avant d'écrire : deux exécutions identiques du même fichier ne s'excluent pas
    already = {i for i, o in chosen if known(conn, o)}
    for i, o in chosen:
        out.append((i, Result() if i in already else journal.apply(o, first)))
    market.appended(conn, import_id, journal.writer.touched)
    return out
