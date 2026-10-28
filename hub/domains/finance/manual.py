"""Positions saisies à la main (lot 6) : placements hors PSD2 (actions et cryptos Revolut), ou
tout compte à positions sans export lisible.

Un CSV dont la première ligne est exactement

    date,account,instrument,name,kind,quantity,price,currency

donne, pour chaque compte cité (`account` = référence externe, `revolut:invest` par exemple),
toutes ses positions à cette date : un relevé de positions, comme un rapport VIAC. `instrument`
est un ISIN, ou un symbole (`AAPL`, `BTC`) ; `kind` vaut stock, etf, fund, bond, crypto ou
other ; `price` est le cours unitaire dans `currency`. Une position absente du fichier n'est
plus détenue à cette date. Les comptes se déclarent avec `hub finance positions add-account`.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, localcontext

from sqlalchemy import Connection

from hub.core.ids import urn
from hub.core.money import DECIMAL_CONTEXT
from hub.domains.finance import assets, catalog, ledger
from hub.domains.finance.assets import AssetError, DocumentError, Result

SOURCE = "positions_csv"
HEADER = ("date", "account", "instrument", "name", "kind", "quantity", "price", "currency")
MAX_BYTES = 5 * 1024 * 1024
MAX_ROWS = 2000


class PositionsError(DocumentError):
    pass


@dataclass(frozen=True)
class Row:
    key: str
    name: str
    kind: str
    quantity: Decimal
    price: Decimal
    currency: str


@dataclass(frozen=True)
class Snapshot:
    account: str
    on_date: str
    rows: list[Row]


@dataclass(frozen=True)
class PositionsFile:
    snapshots: list[Snapshot]

    @property
    def on_date(self) -> str:
        return min((s.on_date for s in self.snapshots), default="")

    def rows(self) -> list[tuple[int, str | None, str | None]]:
        return [(i, None, s.on_date) for i, s in enumerate(self.snapshots)]


def _lines(data: bytes) -> list[str]:
    return data.lstrip(b"\xef\xbb\xbf").decode("utf-8", "replace").splitlines()


def is_positions(data: bytes) -> bool:
    lines = _lines(data[:400])
    return bool(lines) and tuple(c.strip().lower() for c in lines[0].split(",")) == HEADER


def parse(data: bytes) -> PositionsFile:
    if len(data) > MAX_BYTES or not is_positions(data):
        raise PositionsError("pas un fichier de positions")
    reader = csv.DictReader(io.StringIO("\n".join(_lines(data))))
    groups: dict[tuple[str, str], list[Row]] = {}
    for n, raw in enumerate(reader):
        if n >= MAX_ROWS:
            raise PositionsError("trop de lignes")
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items()}
        if not any(row.values()):
            continue
        try:
            on = date.fromisoformat(row["date"]).isoformat()
        except ValueError:
            raise PositionsError(f"ligne {n + 2} : date illisible (AAAA-MM-JJ)") from None
        account = row["account"]
        if not account or len(account) > 60:
            raise PositionsError(f"ligne {n + 2} : compte absent")
        kind = row["kind"].lower() or "other"
        if kind not in assets.KINDS:
            raise PositionsError(f"ligne {n + 2} : type inconnu ({kind})")
        currency = row["currency"].upper()
        try:
            key = assets.instrument_key(row["instrument"], kind)
            quantity = assets.number(row["quantity"])
            price = assets.number(row["price"])
        except AssetError as exc:
            raise PositionsError(f"ligne {n + 2} : {exc}") from None
        if not assets.known_currency(currency):
            raise PositionsError(f"ligne {n + 2} : devise inconnue", "import.unknown_currency")
        if price < 0:
            raise PositionsError(f"ligne {n + 2} : cours négatif")
        groups.setdefault((account, on), []).append(
            Row(key, row["name"][:120], kind, quantity, price, currency)
        )
    if not groups:
        raise PositionsError("fichier vide")
    return PositionsFile([Snapshot(a, d, rows) for (a, d), rows in sorted(groups.items())])


def apply_snapshot(conn: Connection, import_id: str, s: Snapshot, source: str = "manual") -> Result:
    result = Result()
    account = catalog.account_by_ref(conn, s.account)
    if account is None:
        return result.review("unknown_account")
    result.account_id = account.id
    if account.kind not in ("securities", "crypto") or account.currency != "CHF":
        return result.review("currency_mismatch")
    for r in s.rows:
        assets.upsert_instrument(
            conn,
            r.key,
            r.name or None,
            kind=r.kind,
            currency=r.currency,
            symbol=assets.symbol_of(r.key),
        )
        with localcontext(DECIMAL_CONTEXT):
            value = r.quantity * r.price
        if assets.add_holding(
            conn, account.id, s.on_date, r.key, r.quantity, value, r.currency, import_id
        ):
            result.new += 1
        else:
            result.duplicates += 1
        if r.price > 0:
            assets.add_price(conn, r.key, s.on_date, r.price, r.currency, source, import_id)
    if result.new:
        ledger.append_event(
            conn,
            "holdings.recorded",
            urn("finance", "account", account.id),
            {"import_id": import_id, "count": result.new},
        )
    return result


def apply(
    conn: Connection, import_id: str, doc: PositionsFile, indexes: set[int] | None
) -> list[tuple[int, Result]]:
    return [
        (i, apply_snapshot(conn, import_id, s))
        for i, s in enumerate(doc.snapshots)
        if indexes is None or i in indexes
    ]
