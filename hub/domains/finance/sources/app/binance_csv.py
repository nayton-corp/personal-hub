"""Export « Trade History » de Binance (CSV) : les ordres exécutés d'une paire que l'API ne
sert plus (retirée de la cote : BUSD), au registre du compte `crypto:binance` exactement comme
les opérations du collecteur (`exchange`), avec leurs mouvements de parts (audit M15).

Colonnes : `Date(UTC),Pair,Side,Price,Executed,Amount,Fee` ; `Executed`, `Amount` et `Fee`
portent leur actif collé au nombre (`0.0012BTC`). Une ligne est une exécution ; son
identifiant vient de son contenu, un export plus long reconnaît donc les lignes déjà prises.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, localcontext
from typing import Any

from sqlalchemy import Connection

from hub.domains.finance.patrimoine.model import instruments
from hub.domains.finance.patrimoine.model.instruments import DocumentError, Result
from hub.domains.finance.sources.app import exchange, market
from hub.domains.finance.sources.infra.operations import STABLE, Leg, Operation
from hub.kernel.money import DECIMAL_CONTEXT

SOURCE = "binance_csv"
ACCOUNT = "crypto:binance"
HEADER = ("Date(UTC)", "Pair", "Side", "Price", "Executed", "Amount", "Fee")
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
    return SOURCE if tuple(c.strip() for c in first.split(",")) == HEADER else None


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


def parse(data: bytes) -> Statement:
    if len(data) > MAX_BYTES:
        raise BinanceCsvError("fichier trop volumineux")
    text = _text(data)
    if text is None:
        raise BinanceCsvError("texte illisible")
    reader = csv.DictReader(io.StringIO(text))
    if tuple(c.strip() for c in reader.fieldnames or ()) != HEADER:
        raise BinanceCsvError("pas un export « Trade History » de Binance")
    seen: dict[str, int] = {}
    out = []
    for row in reader:
        if not any((v or "").strip() for v in row.values()):
            continue
        when = _WHEN.match((row["Date(UTC)"] or "").strip())
        if not when:
            raise BinanceCsvError("date illisible")
        pair, side = (row["Pair"] or "").strip().upper(), (row["Side"] or "").strip().upper()
        if side not in ("BUY", "SELL"):
            raise BinanceCsvError(f"sens illisible : {side!r}")
        executed, base = _split(row["Executed"] or "", "quantité")
        amount, quote = _split(row["Amount"] or "", "montant")
        fee, fee_asset = _split(row["Fee"] or "0" + quote, "frais")
        try:
            price = Decimal((row["Price"] or "0").replace(",", "").strip())
        except InvalidOperation:
            raise BinanceCsvError("prix illisible") from None
        if pair != base + quote:
            raise BinanceCsvError(f"paire {pair} et actifs {base}/{quote} en désaccord")
        sign = 1 if side == "BUY" else -1
        stamp = f"{when.group(1)}T{when.group(2)}{when.group(3)}{when.group(4)}"
        key = f"csv:{pair}:{stamp}:{side}:{_plain(executed)}:{_plain(amount)}"
        n = seen.get(key, 0)
        seen[key] = n + 1
        legs = [Leg(base, sign * executed, "trade"), Leg(quote, -sign * amount, "trade")]
        if fee:
            legs.append(_fee_leg(fee, fee_asset, base, quote, price))
        out.append(Operation(ACCOUNT, f"{key}:{n}", "trade", when.group(1), tuple(legs)))
    if not out:
        raise BinanceCsvError("export vide")
    out.sort(key=lambda o: (o.on_date, o.id))
    return Statement(out)


def apply(
    conn: Connection, import_id: str, doc: Statement, indexes: set[int] | None
) -> list[tuple[int, Result]]:
    journal = exchange.Journal(conn, import_id)
    first = doc.on_date
    out: list[tuple[int, Any]] = []
    for i, o in enumerate(doc.operations):
        if indexes is None or i in indexes:
            out.append((i, journal.apply(o, first)))
    market.appended(conn, import_id, journal.writer.touched)
    return out
