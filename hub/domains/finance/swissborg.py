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
from dataclasses import dataclass, replace
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation, localcontext

from sqlalchemy import Connection, text

from hub.core import canonical
from hub.core.ids import urn
from hub.core.money import DECIMAL_CONTEXT, Money, base_currency
from hub.domains.finance import assets, catalog, ibkr, ledger, links, manual, valuation, xlsx
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
    fee: Decimal
    fee_usd: Decimal
    net: Decimal
    net_usd: Decimal
    key: str = ""  # identifiant stable de la ligne : écritures sans doublon d'un relevé à l'autre

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
    moves: tuple[Move, ...] = ()


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
        local, utc, kind, currency, gross, gross_usd, fee, fee_usd, net, net_usd = row[:10]
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
                _dec(fee or "0"),
                _dec(fee_usd or "0"),
                _dec(net, signed=kind in DEBITS),
                _dec(net_usd or "0", signed=kind in DEBITS),
            )
        except AssetError as exc:
            raise SwissborgError(f"ligne {n} : {exc}") from None
        out.append(move)
    if not out:
        raise SwissborgError("relevé sans mouvement")
    out.sort(key=lambda m: (m.utc, m.day))
    seen: dict[str, int] = defaultdict(int)
    keyed = []
    for m in out:
        base = f"{m.utc}|{m.kind}|{m.currency}|{m.gross}|{m.net}"
        seen[base] += 1  # lignes identiques à la même seconde (rééquilibrage d'un thème)
        keyed.append(replace(m, key=f"{base}|{seen[base]}"))
    return keyed


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
            days.append(Day(manual.Snapshot(ACCOUNT, day, rows), rate, tuple(moves)))
    return Statement(days)


def _legs(m: Move) -> list[tuple[str, str, str, Decimal, Decimal]]:
    """Écritures d'une ligne : (jambe, code, libellé, montant, contre-valeur USD), signés."""
    c, out = m.currency, []
    if m.kind == "Buy":
        out.append(("buy", "SWISSBORG/TRADE/BUY", f"Achat {c}", m.gross, m.gross_usd))
        out.append(("fee", "SWISSBORG/FEE/TRADE", f"Frais d'échange {c}", -m.fee, -m.fee_usd))
    elif m.kind == "Sell":
        out.append(("sell", "SWISSBORG/TRADE/SELL", f"Vente {c}", -m.gross, -m.gross_usd))
    elif m.kind == "Deposit":
        out.append(("main", "SWISSBORG/DEPOSIT", f"Dépôt {c}", m.gross, m.gross_usd))
        out.append(("fee", "SWISSBORG/FEE/DEPOSIT", f"Frais de dépôt {c}", -m.fee, -m.fee_usd))
    elif m.kind == "Payouts":
        out.append(("main", "SWISSBORG/INCOME/YIELD", f"Rendement {c}", m.gross, m.gross_usd))
        out.append(("fee", "SWISSBORG/FEE/YIELD", f"Frais sur rendement {c}", -m.fee, -m.fee_usd))
    elif m.kind == "Fee Adjustment":
        out.append(("main", "SWISSBORG/FEE/REFUND", f"Remise de frais {c}", m.net, m.net_usd))
    elif m.gross > 0:  # retrait, frais pris sur le brut
        out.append(("main", "SWISSBORG/WITHDRAWAL", f"Retrait {c}", -m.net, -m.net_usd))
        out.append(("fee", "SWISSBORG/FEE/WITHDRAWAL", f"Frais de retrait {c}", -m.fee, -m.fee_usd))
    else:  # frais périodique : net négatif
        out.append(("main", "SWISSBORG/FEE/PERIODIC", f"Frais périodiques {c}", m.net, m.net_usd))
    return out


def _delta_usd(m: Move) -> Decimal:
    if m.kind in CREDITS or m.gross == 0:
        return m.net_usd
    return -m.gross_usd


class _Values:
    """Montant d'une ligne en devise de base : la devise elle-même, sinon sa contre-valeur USD
    au change du jour (celui du relevé, sinon le dernier connu)."""

    def __init__(self, conn: Connection) -> None:
        self.fx = valuation.FxTable(conn, ["USD"])

    def of(self, m: Move, amount: Decimal, usd: Decimal) -> int | None:
        if m.currency == self.fx.base:
            return Money.from_decimal(amount, self.fx.base).minor
        return self.fx.convert(usd, "USD", m.day)


def _day_before(on: str) -> str:
    return (date.fromisoformat(on) - timedelta(days=1)).isoformat()


def apply(
    conn: Connection, import_id: str, doc: Statement, indexes: set[int] | None
) -> list[tuple[int, Result]]:
    days = [(i, d) for i, d in enumerate(doc.days) if indexes is None or i in indexes]
    if base_currency() == "CHF":
        for _i, d in days:
            if d.usd_chf is not None:
                assets.add_fx(conn, d.snapshot.on_date, "USD", "CHF", d.usd_chf, SOURCE)
    account = catalog.account_by_ref(conn, ACCOUNT)
    if (
        account is not None
        and days
        and not conn.execute(
            text("SELECT 1 FROM entries WHERE account_id = :a LIMIT 1"), {"a": account.id}
        ).first()
    ):
        from hub.domains.finance.importer import open_account  # import circulaire

        open_account(
            conn, account.id, _day_before(days[0][1].snapshot.on_date), 0, account.currency
        )
    values = _Values(conn)
    writer = ibkr.Writer(conn, import_id, ACCOUNT, Result(), namespace=SOURCE)
    out = []
    for i, d in days:
        result = manual.apply_snapshot(conn, import_id, d.snapshot, SOURCE)
        if account is not None and result.status == "applied":
            writer.result = result
            for m in d.moves:
                _write_move(conn, import_id, writer, account, values, m)
        out.append((i, result))
    for account_id, count in sorted(writer.touched.items()):
        ledger.append_event(
            conn,
            "entries.appended",
            urn("finance", "account", account_id),
            {"import_id": import_id, "count": count},
        )
    return out


def _write_move(
    conn: Connection,
    import_id: str,
    writer: ibkr.Writer,
    account: catalog.Account,
    values: _Values,
    m: Move,
) -> None:
    """Les écritures de la ligne (montant en devise de base, quantité en libellé) et son
    mouvement de parts dans `trades`, qui donne le prix de revient."""
    legs = [
        (leg, code, label, q, usd, values.of(m, q, usd)) for leg, code, label, q, usd in _legs(m)
    ]
    cost = values.of(m, m.delta, _delta_usd(m))
    peer = None
    if m.kind in ("Deposit", "Withdrawal") and not assets.known_currency(m.currency):
        # l'autre côté sur un autre de mes comptes (Binance, Ledger) : sa valeur
        leg, code, label, q, usd, _v = legs[0]
        peer = links.counterpart(conn, ACCOUNT, m.currency, m.day, q)
        if peer:
            legs[0] = (leg, code, label, q, usd, -peer[1])
            if cost is not None and all(v is not None for *_x, v in legs):
                cost = sum(int(v or 0) for *_x, v in legs)
    if cost is None or any(v is None for *_x, v in legs):
        writer.result.review("missing_fx")
        return
    for leg, code, label, qty, usd, amount in legs:
        if amount:
            # quantité de la jambe (le net d'un retrait : ce qui arrive sur le portefeuille),
            # pour l'apparier à son arrivée sur un autre compte
            detail: dict[str, str | int] = {
                "quantity": assets.qty_text(qty),
                "currency": m.currency,
                "usd": str(usd),
            }
            if peer and leg == "main":
                detail["peer"] = peer[0]
            writer.entry(
                account,
                f"{m.key}|{leg}",
                m.day,
                amount,
                code,
                label,
                counterparty="SwissBorg",
                remittance=f"{assets.qty_text(qty)} {m.currency}",
                fx_json=canonical.dumps(detail),
            )
    if m.delta == 0:
        return
    key, _kind, _name = _key(m.currency)
    trade_key = ledger.dedup_hash(f"{SOURCE}|{m.key}|trade")
    if conn.execute(text("SELECT 1 FROM trades WHERE dedup_key = :k"), {"k": trade_key}).first():
        return
    ledger.append(
        conn,
        "trades",
        {
            "account_id": account.id,
            "trade_date": m.day,
            "isin": key,
            "quantity": assets.qty_text(m.delta),
            "amount_minor": cost,
            "currency": account.currency,
            "dedup_key": trade_key,
            "import_id": import_id,
            "created_at": writer.created,
        },
    )
