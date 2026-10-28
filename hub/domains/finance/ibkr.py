"""Relevés IBKR par Flex Query (lot 6) : lecture du XML et écriture au registre.

Un compte IBKR devient plusieurs comptes de titres du registre : un par devise de liquidités
(`ibkr:<compte>:<DEVISE>`) et un pour les titres (`ibkr:<compte>:titres`, dans la devise de
base du compte), valorisé par ses positions. Seul le compte de titres se déclare
(`hub finance ibkr add-account`) ; les comptes de liquidités se créent au premier relevé qui
les cite, et chaque compte s'ouvre la veille du premier relevé importé, au solde de départ que
donne IBKR (zéro pour les titres).

Écritures, toutes identifiées par le `transactionID` d'IBKR :

- un achat ou une vente de titres : la contrevaleur dans le compte de liquidités de sa devise
  (IBKR/TRADE/BUY|SELL), la même contrevaleur en devise de base dans le compte de titres, une
  ligne de `trades` et la commission à part (IBKR/FEE/COMMISSION) ;
- un change (catégorie CASH) : les deux montants réels, un dans chaque compte (IBKR/FX), avec
  le cours dans `fx_json` ;
- un mouvement de liquidités : versement ou retrait (IBKR/DEPOSIT), dividende, intérêt, impôt
  à la source (IBKR/INCOME/…), frais (IBKR/FEE/…), autre (IBKR/OTHER).

Les positions (OpenPositions, niveau résumé) deviennent un relevé de positions avec leurs
cours, les soldes de fin (CashReport) des points de contrôle, et les cours de change
(ConversionRates) des lignes de `fx_rates`. Comme pour VIAC, les écarts de soldes sont signalés,
jamais bloquants : le relevé est une observation d'IBKR.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal, localcontext

from lxml import etree
from lxml.etree import _Element
from sqlalchemy import Connection, text

from hub.core import canonical
from hub.core.clock import now_iso
from hub.core.ids import urn
from hub.core.money import DECIMAL_CONTEXT, Money, base_currency
from hub.domains.finance import assets, catalog, ledger, rules
from hub.domains.finance.assets import AssetError, DocumentError, Result

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


# --- lecture --------------------------------------------------------------------------------


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
        return assets.number(raw)
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
    if assets.ISIN.match(isin):
        return isin, symbol
    if conid.isdigit():
        return f"IBKR:{conid}", symbol
    if symbol:
        return assets.instrument_key(symbol), symbol
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


# --- écriture -------------------------------------------------------------------------------


def _day_before(on: str) -> str:
    return (date.fromisoformat(on) - timedelta(days=1)).isoformat()


def _minor(amount: Decimal, currency: str) -> int:
    return Money.from_decimal(amount, currency).minor


def _ensure_cash(
    conn: Connection, titles: catalog.Account, account: str, ccy: str
) -> catalog.Account:
    found = catalog.account_by_ref(conn, cash_ref(account, ccy))
    if found is not None:
        return found
    return catalog.add_account(
        conn,
        institution=INSTITUTION,
        name=f"{titles.name} {ccy}",
        kind="securities",
        currency=ccy,
        external_ref=cash_ref(account, ccy),
    )


class _Writer:
    """Écritures d'un relevé, catégorisées par les règles système (codes IBKR/…)."""

    def __init__(self, conn: Connection, import_id: str, account: str, result: Result) -> None:
        self.conn = conn
        self.import_id = import_id
        self.account = account
        self.result = result
        self.ruleset = rules.load(conn)
        self.created = now_iso()
        self.touched: dict[str, int] = {}
        self.openings: dict[str, str | None] = {}

    def opened(self, account_id: str) -> str | None:
        if account_id not in self.openings:
            self.openings[account_id] = assets.opening_date(self.conn, account_id)
        return self.openings[account_id]

    def entry(
        self,
        target: catalog.Account,
        key: str,
        on: str,
        amount: int,
        code: str,
        label: str,
        *,
        counterparty: str | None = None,
        remittance: str = "",
        fx_json: str | None = None,
    ) -> None:
        dedup_key = ledger.dedup_hash(f"ibkr|{self.account}|{key}")
        if self.conn.execute(
            text("SELECT 1 FROM entries WHERE dedup_key = :k"), {"k": dedup_key}
        ).first():
            self.result.duplicates += 1
            return
        opened = self.opened(target.id)
        if opened is None or on <= opened:
            self.result.review("before_opening" if opened else "no_opening")
            return
        e = ledger.NewEntry(
            account_id=target.id,
            booking_date=on,
            value_date=on,
            amount_minor=amount,
            currency=target.currency,
            counterparty=counterparty,
            label=label,
            remittance=remittance,
            bank_ref=key.split("|")[0][:60],
            bank_tx_code=code,
            fx_json=fx_json,
            dedup_key=dedup_key,
            import_id=self.import_id,
        )
        seq, _ = ledger.append_entry(self.conn, e, self.created)
        won = self.ruleset.winner(
            rules.Target(
                amount,
                ledger.search_text(counterparty, label, remittance),
                None,
                code,
                None,
            )
        )
        if won is not None:
            rules.categorize(self.conn, seq, won, proposal_id=None, created_at=self.created)
        self.result.new += 1
        self.touched[target.id] = self.touched.get(target.id, 0) + 1


def _base_amount(t: Trade, base: str) -> Decimal | None:
    """Contrevaleur d'un achat (positive) ou d'une vente (négative) en devise de base."""
    if t.currency == base:
        return -t.proceeds
    if t.fx_to_base is None:
        return None
    with localcontext(DECIMAL_CONTEXT):
        return -t.proceeds * t.fx_to_base


def apply_statement(conn: Connection, import_id: str, st: Statement) -> Result:
    result = Result()
    titles = catalog.account_by_ref(conn, titles_ref(st.account))
    if titles is None:
        return result.review("unknown_account")
    result.account_id = titles.id
    if st.base_currency and st.base_currency != titles.currency:
        return result.review("currency_mismatch")
    unknown = sorted(c for c in st.currencies if not assets.known_currency(c))
    if unknown:
        return result.review("unknown_currency")
    # rien d'écrit à moitié : un relevé qui doit attendre ne laisse aucune trace
    savepoint = conn.begin_nested()
    try:
        _write(conn, import_id, st, titles, result)
    except BaseException:
        savepoint.rollback()
        raise
    if result.status == "needs_review":
        savepoint.rollback()
        result.new = result.duplicates = 0
        result.reasons -= OBSERVATIONS  # rien n'a été écrit : seul le blocage compte
    else:
        savepoint.commit()
    return result


def _write(
    conn: Connection, import_id: str, st: Statement, titles: catalog.Account, result: Result
) -> None:
    base = titles.currency
    cash = {c: _ensure_cash(conn, titles, st.account, c) for c in sorted(st.currencies)}
    starting = {c.currency: c.starting for c in st.cash}
    # ouverture : la veille du premier relevé importé, au solde de départ d'IBKR
    opening_day = _day_before(st.from_date)
    for target, amount in [(titles, Decimal(0))] + [
        (a, starting.get(c) or Decimal(0)) for c, a in cash.items()
    ]:
        if (
            assets.opening_date(conn, target.id) is None
            and not conn.execute(
                text("SELECT 1 FROM entries WHERE account_id = :a LIMIT 1"), {"a": target.id}
            ).first()
        ):
            from hub.domains.finance.importer import open_account  # import circulaire

            open_account(
                conn, target.id, opening_day, _minor(amount, target.currency), target.currency
            )

    w = _Writer(conn, import_id, st.account, result)
    for t in st.trades:
        side = "BUY" if t.quantity > 0 else "SELL"
        if t.category == "CASH":
            left, right = t.symbol.split(".")
            fx = canonical.dumps({"pair": t.symbol, "rate": assets.price_text(t.price)})
            label = f"Change {left}/{right}"
            w.entry(
                cash[left],
                f"{t.tx_id}|fx|{left}",
                t.on_date,
                _minor(t.quantity, left),
                "IBKR/FX",
                label,
                fx_json=fx,
            )
            w.entry(
                cash[t.currency],
                f"{t.tx_id}|fx|{t.currency}",
                t.on_date,
                _minor(t.proceeds, t.currency),
                "IBKR/FX",
                label,
                fx_json=fx,
            )
        else:
            cost = _base_amount(t, base)
            if cost is None:
                result.review("missing_fx")
                continue
            label = f"{'Achat' if side == 'BUY' else 'Vente'} {t.symbol or t.name}"
            code = f"IBKR/TRADE/{side}"
            w.entry(
                cash[t.currency],
                f"{t.tx_id}|cash",
                t.on_date,
                _minor(t.proceeds, t.currency),
                code,
                label,
                counterparty=t.name,
            )
            w.entry(
                titles,
                f"{t.tx_id}|titres",
                t.on_date,
                _minor(cost, base),
                code,
                label,
                counterparty=t.name,
            )
            assets.upsert_instrument(
                conn, t.key, t.name, kind=t.kind, currency=t.currency, symbol=t.symbol or None
            )
            trade_key = ledger.dedup_hash(f"ibkr|{st.account}|{t.tx_id}|trade")
            if not conn.execute(
                text("SELECT 1 FROM trades WHERE dedup_key = :k"), {"k": trade_key}
            ).first():
                ledger.append(
                    conn,
                    "trades",
                    {
                        "account_id": titles.id,
                        "trade_date": t.on_date,
                        "isin": t.key,
                        "quantity": assets.qty_text(t.quantity),
                        "amount_minor": _minor(cost, base),
                        "currency": base,
                        "dedup_key": trade_key,
                        "import_id": import_id,
                        "created_at": w.created,
                    },
                )
            if t.price > 0:
                assets.add_price(
                    conn, t.key, t.on_date, t.price, t.currency, "ibkr_trade", import_id
                )
        if t.commission:
            w.entry(
                cash[t.commission_currency],
                f"{t.tx_id}|commission",
                t.on_date,
                _minor(t.commission, t.commission_currency),
                "IBKR/FEE/COMMISSION",
                "Commission",
                counterparty=t.name or None,
            )

    for ct in st.cash_txs:
        w.entry(
            cash[ct.currency],
            f"{ct.tx_id}|cash",
            ct.on_date,
            _minor(ct.amount, ct.currency),
            ct.code,
            LABELS.get(ct.code, "Mouvement IBKR"),
            remittance=ct.description,
        )

    held = 0
    if st.positions is not None:
        for p in st.positions:
            if not assets.known_currency(p.currency):
                result.reasons.add("unknown_currency")
                continue
            assets.upsert_instrument(
                conn, p.key, p.name, kind=p.kind, currency=p.currency, symbol=p.symbol or None
            )
            if assets.add_holding(
                conn,
                titles.id,
                p.on_date,
                p.key,
                p.quantity,
                p.value,
                p.currency,
                import_id,
                p.cost_price,
            ):
                held += 1
            else:
                result.duplicates += 1
            if p.mark_price > 0:
                assets.add_price(
                    conn, p.key, p.on_date, p.mark_price, p.currency, "ibkr_flex", import_id
                )
        result.new += held

    for r in st.rates:
        if r.quote == base_currency() and assets.known_currency(r.base):
            assets.add_fx(conn, r.on_date, r.base, r.quote, r.rate, "ibkr")

    # soldes de fin : points de contrôle et comparaison au registre (observation)
    for c in st.cash:
        if c.ending is None or c.currency not in cash:
            continue
        target = cash[c.currency]
        ending = _minor(c.ending, c.currency)
        known = conn.execute(
            text(
                "SELECT amount_minor FROM checkpoints WHERE account_id = :a AND on_date = :d "
                "AND kind = 'CLBD'"
            ),
            {"a": target.id, "d": st.to_date},
        ).scalar_one_or_none()
        if known is None:
            ledger.append(
                conn,
                "checkpoints",
                {
                    "account_id": target.id,
                    "on_date": st.to_date,
                    "kind": "CLBD",
                    "amount_minor": ending,
                    "import_id": import_id,
                },
            )
        elif known != ending:
            result.reasons.add("checkpoint_conflict")
        balance = conn.execute(
            text(
                "SELECT coalesce(sum(amount_minor), 0) FROM entries WHERE account_id = :a "
                "AND booking_date <= :d AND kind != 'correction'"
            ),
            {"a": target.id, "d": st.to_date},
        ).scalar_one()
        if balance != ending:
            result.reasons.add("ledger_check_failed")

    for account_id, count in sorted(w.touched.items()):
        ledger.append_event(
            conn,
            "entries.appended",
            urn("finance", "account", account_id),
            {"import_id": import_id, "count": count},
        )
    if held:
        ledger.append_event(
            conn,
            "holdings.recorded",
            urn("finance", "account", titles.id),
            {"import_id": import_id, "count": held},
        )
