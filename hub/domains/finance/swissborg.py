"""Relevé de compte SwissBorg (« Account statement », .xlsx) : l'historique des soldes par actif.

SwissBorg n'a pas d'API publique. Son export (Profil → Documents → Relevé de compte, format
Excel, toute la période) liste chaque mouvement : achat, vente, dépôt, retrait, rendement,
avec sa contre-valeur en USD. Le fichier se relit depuis le premier mouvement : les soldes
s'additionnent, puis chaque jour où un solde bouge devient un relevé complet des positions du
compte `crypto:swissborg`, comme le CSV de positions (`manual`). Le cours de chaque actif ce
jour-là est celui des mouvements du fichier (contre-valeur USD ÷ quantité), le change USD/CHF
celui des mouvements en francs. Un franc (ou un euro) en attente est une position `SYM:CHF`.

Sens des montants : achat, dépôt, rendement et remise de frais créditent le net ; vente et
retrait débitent le brut (les frais d'un retrait sont pris dessus) ; un frais périodique est un
retrait de brut nul et de net négatif, qui débite ce net.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation, localcontext

from sqlalchemy import Connection

from hub.core.money import DECIMAL_CONTEXT
from hub.domains.finance import assets, manual, xlsx
from hub.domains.finance.assets import AssetError, DocumentError, Result

SOURCE = "swissborg"
ACCOUNT = "crypto:swissborg"
HEADER = (
    "Local time",
    "Time in UTC",
    "Type",
    "Currency",
    "Gross amount",
    "Gross amount (USD)",
    "Fee",
    "Fee (USD)",
    "Net amount",
    "Net amount (USD)",
    "Note",
)
CREDITS = frozenset({"Buy", "Deposit", "Payouts", "Fee Adjustment"})
DEBITS = frozenset({"Sell", "Withdrawal"})
HEADER_SEARCH = 40  # lignes d'en-tête du relevé (nom, adresse, période) avant le tableau
QUANTUM = Decimal("1e-12")


class SwissborgError(DocumentError):
    pass


@dataclass(frozen=True)
class Move:
    day: str
    utc: str
    kind: str
    currency: str
    gross: Decimal
    gross_usd: Decimal
    net: Decimal

    @property
    def delta(self) -> Decimal:
        if self.kind in CREDITS:
            return self.net
        # frais périodique : brut nul, net négatif (les frais) ; retrait : frais pris sur le brut
        return -self.gross + min(self.net, Decimal(0))


@dataclass(frozen=True)
class Day:
    snapshot: manual.Snapshot
    usd_chf: Decimal | None  # 1 USD en CHF selon les mouvements en francs du jour


@dataclass(frozen=True)
class Statement:
    days: list[Day]

    @property
    def on_date(self) -> str:
        return self.days[0].snapshot.on_date if self.days else ""

    def rows(self) -> list[tuple[int, str | None, str | None]]:
        return [(i, None, d.snapshot.on_date) for i, d in enumerate(self.days)]


def _header_row(table: list[list[str]]) -> int | None:
    for i, row in enumerate(table[:HEADER_SEARCH]):
        if tuple(row[: len(HEADER)]) == HEADER:
            return i
    return None


def detect(name: str, data: bytes) -> str | None:
    if not xlsx.is_xlsx(name, data):
        return None
    try:
        return SOURCE if _header_row(xlsx.rows(data)) is not None else None
    except xlsx.XlsxError:
        return None


def _dec(text: str, signed: bool = False) -> Decimal:
    try:
        with localcontext(DECIMAL_CONTEXT):
            out = Decimal(text)
    except InvalidOperation:
        raise AssetError("nombre illisible") from None
    if not out.is_finite() or (out < 0 and not signed):
        raise AssetError("montant négatif ou illisible")
    return out


def _moves(table: list[list[str]], start: int) -> list[Move]:
    out = []
    for n, raw in enumerate(table[start + 1 :], start=start + 2):
        row = raw + [""] * (len(HEADER) - len(raw))
        if not any(row):
            continue
        local, utc, kind, currency, gross, gross_usd, _fee, _fee_usd, net = row[:9]
        if kind not in CREDITS | DEBITS:
            raise SwissborgError(f"ligne {n} : type de mouvement inconnu ({kind[:30]})")
        try:
            day = date.fromisoformat(local[:10]).isoformat()
            date.fromisoformat(utc[:10])
        except ValueError:
            raise SwissborgError(f"ligne {n} : date illisible") from None
        try:
            assets.instrument_key(currency, "crypto")
            move = Move(
                day,
                utc,
                kind,
                currency.upper(),
                _dec(gross),
                _dec(gross_usd),
                _dec(net, signed=kind in DEBITS),
            )
        except AssetError as exc:
            raise SwissborgError(f"ligne {n} : {exc}") from None
        out.append(move)
    if not out:
        raise SwissborgError("relevé sans mouvement")
    return sorted(out, key=lambda m: (m.utc, m.day))


def _key(currency: str) -> tuple[str, str, str]:
    """(clé d'instrument, type, nom) ; une devise est une position de liquidités."""
    if assets.known_currency(currency):
        return f"SYM:{currency}", "other", f"{currency} en attente"
    return assets.crypto_key(currency), "crypto", assets.CRYPTO_NAMES.get(currency, "")


def parse(data: bytes) -> Statement:
    try:
        table = xlsx.rows(data)
    except xlsx.XlsxError as exc:
        raise SwissborgError(str(exc)) from None
    start = _header_row(table)
    if start is None:
        raise SwissborgError("pas un relevé SwissBorg")
    by_day: dict[str, list[Move]] = defaultdict(list)
    for m in _moves(table, start):
        by_day[m.day].append(m)
    balances: dict[str, Decimal] = defaultdict(Decimal)
    days = []
    with localcontext(DECIMAL_CONTEXT):
        for day in sorted(by_day):
            moves = by_day[day]
            touched = set()
            qty: dict[str, Decimal] = defaultdict(Decimal)
            usd: dict[str, Decimal] = defaultdict(Decimal)
            for m in moves:
                balances[m.currency] += m.delta
                touched.add(m.currency)
                qty[m.currency] += m.gross
                usd[m.currency] += m.gross_usd
            negative = [c for c, b in balances.items() if b < -QUANTUM]
            if negative:
                raise SwissborgError(f"{day} : solde {negative[0]} négatif (relevé incomplet ?)")
            rows = []
            for currency in sorted(balances):
                held = balances[currency].quantize(QUANTUM)
                if held <= 0 and currency not in touched:
                    continue
                key, kind, name = _key(currency)
                if kind == "other":
                    price, price_ccy = Decimal(1), currency
                elif qty[currency] > 0 and usd[currency] > 0:
                    price, price_ccy = usd[currency] / qty[currency], "USD"
                else:
                    price, price_ccy = Decimal(0), "USD"  # dernier cours connu
                rows.append(manual.Row(key, name, kind, max(held, Decimal(0)), price, price_ccy))
            rate = (
                qty["CHF"] / usd["CHF"] if qty.get("CHF", 0) > 0 and usd.get("CHF", 0) > 0 else None
            )
            days.append(Day(manual.Snapshot(ACCOUNT, day, rows), rate))
    return Statement(days)


def apply(
    conn: Connection, import_id: str, doc: Statement, indexes: set[int] | None
) -> list[tuple[int, Result]]:
    out = []
    for i, d in enumerate(doc.days):
        if indexes is not None and i not in indexes:
            continue
        if d.usd_chf is not None:
            assets.add_fx(conn, d.snapshot.on_date, "USD", "CHF", d.usd_chf, SOURCE)
        out.append((i, manual.apply_snapshot(conn, import_id, d.snapshot, SOURCE)))
    return out
