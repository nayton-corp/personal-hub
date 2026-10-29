"""Relevés IBKR par Flex Query (lot 6) : lecture du XML (liquidités par devise, positions, ordres,
mouvements de liquidités, cours de change), sans rien écrire."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from lxml import etree
from lxml.etree import _Element

from hub.domains.finance.patrimoine.model import instruments
from hub.domains.finance.patrimoine.model.instruments import AssetError, DocumentError

SOURCE = "ibkr_flex"
INSTITUTION = "IBKR"
MAX_BYTES = 30 * 1024 * 1024
STOCKLIKE = {"STK": "stock", "FUND": "fund", "BOND": "bond", "ETF": "etf"}
# types de CashTransaction → code du registre
CASH_TYPES = {
    "deposits/withdrawals": "IBKR/DEPOSIT",
    "deposits & withdrawals": "IBKR/DEPOSIT",
    "dividends": "IBKR/INCOME/DIVIDEND",
    "payment in lieu of dividends": "IBKR/INCOME/DIVIDEND",
    "withholding tax": "IBKR/INCOME/TAX",
    "broker interest received": "IBKR/INCOME/INTEREST",
    "bond interest received": "IBKR/INCOME/INTEREST",
    "broker interest paid": "IBKR/FEE/INTEREST",
    "bond interest paid": "IBKR/FEE/INTEREST",
    "other fees": "IBKR/FEE/OTHER",
    "commission adjustments": "IBKR/FEE/COMMISSION",
    "advisor fees": "IBKR/FEE/OTHER",
}
LABELS = {
    "IBKR/DEPOSIT": "Versement IBKR",
    "IBKR/INCOME/DIVIDEND": "Dividende",
    "IBKR/INCOME/TAX": "Impôt à la source",
    "IBKR/INCOME/INTEREST": "Intérêts",
    "IBKR/FEE/INTEREST": "Intérêts débiteurs",
    "IBKR/FEE/OTHER": "Frais IBKR",
    "IBKR/FEE/COMMISSION": "Commission",
    "IBKR/OTHER": "Mouvement IBKR",
}
# écarts signalés sur un relevé appliqué, jamais bloquants
OBSERVATIONS = frozenset({"ledger_check_failed", "checkpoint_conflict"})


class FlexError(DocumentError):
    pass


def titles_ref(account: str) -> str:
    return f"ibkr:{account}:titres"


def cash_ref(account: str, currency: str) -> str:
    return f"ibkr:{account}:{currency}"


@dataclass(frozen=True)
class Cash:
    currency: str
    starting: Decimal | None
    ending: Decimal | None


@dataclass(frozen=True)
class Position:
    key: str
    symbol: str
    name: str
    kind: str
    currency: str
    quantity: Decimal
    mark_price: Decimal
    value: Decimal
    cost_price: Decimal | None
    on_date: str


@dataclass(frozen=True)
class Trade:
    tx_id: str
    on_date: str
    category: str  # STK, CASH…
    key: str  # instrument (vide pour un change)
    symbol: str
    name: str
    kind: str
    currency: str
    quantity: Decimal  # signée : achat positif
    price: Decimal
    proceeds: Decimal  # signé, dans `currency` : achat négatif
    commission: Decimal  # négative
    commission_currency: str
    fx_to_base: Decimal | None


@dataclass(frozen=True)
class CashTx:
    tx_id: str
    on_date: str
    currency: str
    code: str
    amount: Decimal
    description: str


@dataclass(frozen=True)
class Rate:
    on_date: str
    base: str
    quote: str
    rate: Decimal


@dataclass(frozen=True)
class Statement:
    index: int
    account: str
    base_currency: str | None
    from_date: str
    to_date: str
    cash: list[Cash] = field(default_factory=list)
    positions: list[Position] | None = None  # None : section absente de la requête
    trades: list[Trade] = field(default_factory=list)
    cash_txs: list[CashTx] = field(default_factory=list)
    rates: list[Rate] = field(default_factory=list)

    @property
    def currencies(self) -> set[str]:
        out = {c.currency for c in self.cash}
        out |= {t.currency for t in self.trades}
        out |= {t.commission_currency for t in self.trades if t.commission}
        out |= {t.symbol.split(".")[0] for t in self.trades if t.category == "CASH"}
        out |= {c.currency for c in self.cash_txs}
        return out


@dataclass(frozen=True)
class FlexFile:
    statements: list[Statement]

    @property
    def on_date(self) -> str:
        return min((s.from_date for s in self.statements), default="")

    def rows(self) -> list[tuple[int, str | None, str | None]]:
        return [(s.index, s.from_date, s.to_date) for s in self.statements]


def _parser() -> etree.XMLParser:
    return etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False, load_dtd=False)


def _root(data: bytes) -> _Element | None:
    if len(data) > MAX_BYTES or b"<!ENTITY" in data[:4096] or b"<!DOCTYPE" in data[:4096]:
        return None
    try:
        root = etree.fromstring(data, _parser())
    except etree.XMLSyntaxError:
        return None
    return root if root.tag == "FlexQueryResponse" else None


def is_flex(data: bytes) -> bool:
    return data.lstrip()[:200].find(b"FlexQueryResponse") >= 0 and _root(data) is not None


def iso_date(value: str | None) -> str | None:
    """'20261027', '2026-10-27', '20261027;093000', '2026-10-27, 09:30:00' ou '10/27/2026'."""
    if not value:
        return None
    v = value.strip()
    try:
        if m := re.match(r"^(\d{4})(\d{2})(\d{2})", v):
            return date(int(m[1]), int(m[2]), int(m[3])).isoformat()
        if m := re.match(r"^(\d{4})-(\d{2})-(\d{2})", v):
            return date(int(m[1]), int(m[2]), int(m[3])).isoformat()
        if m := re.match(r"^(\d{2})/(\d{2})/(\d{4})", v):
            return date(int(m[3]), int(m[1]), int(m[2])).isoformat()
    except ValueError:
        pass
    raise FlexError("date illisible")


def _dec(el: _Element, name: str) -> Decimal | None:
    raw = el.get(name)
    if raw is None or raw.strip() in ("", "--", "N/A"):
        return None
    try:
        return instruments.number(raw)
    except AssetError:
        raise FlexError(f"nombre illisible ({name})") from None


def _need(el: _Element, name: str) -> Decimal:
    value = _dec(el, name)
    if value is None:
        raise FlexError(f"champ absent ({name})")
    return value


def _date_of(el: _Element, *names: str) -> str:
    for n in names:
        found = iso_date(el.get(n))
        if found:
            return found
    raise FlexError("ligne sans date")


def _key(el: _Element) -> tuple[str, str]:
    """(clé d'instrument, symbole)."""
    isin = (el.get("isin") or "").strip().upper()
    symbol = (el.get("symbol") or "").strip().upper()[:20]
    conid = (el.get("conid") or "").strip()
    if instruments.ISIN.match(isin):
        return isin, symbol
    if conid.isdigit():
        return f"IBKR:{conid}", symbol
    if symbol:
        return instruments.instrument_key(symbol), symbol
    raise FlexError("instrument sans ISIN ni identifiant")


def _level(el: _Element, *wanted: str) -> bool:
    """Niveau de détail gardé : une ligne par position (SUMMARY, pas LOT), par exécution
    (EXECUTION, pas ORDER ni CLOSED_LOT), par mouvement de liquidités (DETAIL)."""
    level = (el.get("levelOfDetail") or "").upper()
    return level == "" or level in wanted


def _statement(index: int, st: _Element) -> Statement:
    account = (st.get("accountId") or "").strip()
    if not re.match(r"^[A-Z0-9]{4,20}$", account):
        raise FlexError("relevé sans numéro de compte")
    info = st.find("AccountInformation")
    base = (info.get("currency") or "").upper() if info is not None else None
    from_date = _date_of(st, "fromDate")
    to_date = _date_of(st, "toDate")

    cash = []
    for c in st.iterfind("CashReport/CashReportCurrency"):
        ccy = (c.get("currency") or "").upper()
        if not re.match(r"^[A-Z]{3}$", ccy):
            continue  # BASE_SUMMARY : total en devise de base
        cash.append(Cash(ccy, _dec(c, "startingCash"), _dec(c, "endingCash")))

    positions = None
    section = st.find("OpenPositions")
    if section is not None:
        positions = []
        for p in section.iterfind("OpenPosition"):
            if not _level(p, "SUMMARY"):
                continue
            key, symbol = _key(p)
            category = (p.get("assetCategory") or "").upper()
            positions.append(
                Position(
                    key=key,
                    symbol=symbol,
                    name=(p.get("description") or symbol or key)[:120],
                    kind=STOCKLIKE.get(category, "other"),
                    currency=(p.get("currency") or "").upper(),
                    quantity=_need(p, "position"),
                    mark_price=_need(p, "markPrice"),
                    value=_need(p, "positionValue"),
                    cost_price=_dec(p, "costBasisPrice"),
                    on_date=iso_date(p.get("reportDate")) or to_date,
                )
            )

    trades = []
    for t in st.iterfind("Trades/Trade"):
        if not _level(t, "EXECUTION"):
            continue
        category = (t.get("assetCategory") or "").upper()
        tx_id = (t.get("transactionID") or t.get("tradeID") or "").strip()
        if not tx_id:
            raise FlexError("opération sans identifiant")
        if category == "CASH":
            key, symbol = "", (t.get("symbol") or "").upper()
            if not re.match(r"^[A-Z]{3}\.[A-Z]{3}$", symbol):
                raise FlexError("change illisible")
        else:
            key, symbol = _key(t)
        quantity = _need(t, "quantity")
        side = (t.get("buySell") or "").upper()
        if side.startswith("SELL") and quantity > 0:
            quantity = -quantity
        trades.append(
            Trade(
                tx_id=tx_id,
                on_date=_date_of(t, "tradeDate", "dateTime", "settleDateTarget"),
                category=category,
                key=key,
                symbol=symbol,
                name=(t.get("description") or symbol or key)[:120],
                kind=STOCKLIKE.get(category, "other"),
                currency=(t.get("currency") or "").upper(),
                quantity=quantity,
                price=_dec(t, "tradePrice") or Decimal(0),
                proceeds=_need(t, "proceeds"),
                commission=_dec(t, "ibCommission") or Decimal(0),
                commission_currency=(
                    t.get("ibCommissionCurrency") or t.get("currency") or ""
                ).upper(),
                fx_to_base=_dec(t, "fxRateToBase"),
            )
        )

    cash_txs = []
    for c in st.iterfind("CashTransactions/CashTransaction"):
        if not _level(c, "DETAIL"):
            continue
        kind = (c.get("type") or "").strip().lower()
        tx_id = (c.get("transactionID") or "").strip()
        on = _date_of(c, "settleDate", "dateTime", "reportDate")
        amount = _need(c, "amount")
        if not tx_id:
            tx_id = f"{on}|{kind}|{amount}|{(c.get('description') or '')[:40]}"
        cash_txs.append(
            CashTx(
                tx_id=tx_id,
                on_date=on,
                currency=(c.get("currency") or "").upper(),
                code=CASH_TYPES.get(kind, "IBKR/OTHER"),
                amount=amount,
                description=(c.get("description") or "")[:200],
            )
        )

    rates = []
    for r in st.iterfind("ConversionRates/ConversionRate"):
        rate = _dec(r, "rate")
        rated = iso_date(r.get("reportDate"))
        frm, to = (r.get("fromCurrency") or "").upper(), (r.get("toCurrency") or "").upper()
        if rate and rate > 0 and rated and frm != to:
            rates.append(Rate(rated, frm, to, rate))

    return Statement(
        index=index,
        account=account,
        base_currency=base or None,
        from_date=from_date,
        to_date=to_date,
        cash=cash,
        positions=positions,
        trades=trades,
        cash_txs=cash_txs,
        rates=rates,
    )


def parse(data: bytes) -> FlexFile:
    root = _root(data)
    if root is None:
        raise FlexError("pas un relevé Flex Query IBKR")
    statements = [
        _statement(i, st) for i, st in enumerate(root.iterfind("FlexStatements/FlexStatement"))
    ]
    if not statements:
        raise FlexError("relevé Flex vide")
    return FlexFile(statements)
