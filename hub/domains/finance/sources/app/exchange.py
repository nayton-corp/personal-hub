"""Opérations d'une plateforme crypto (Binance) : la liste `operations` d'un fichier
`hub.market.v1`, au registre du compte `crypto:<plateforme>`.

Une opération a des jambes, chacune un actif, une quantité signée et un rôle : `deposit`,
`withdrawal` (crypto ou monnaie qui entre ou sort de la plateforme), `trade` (achat, vente,
conversion), `income` (récompense, distribution) et `fee`. Chaque jambe devient une écriture
en devise de base (codes `EXCHANGE/…`, quantité et actif dans le détail), et l'opération un
mouvement de parts par actif dans `trades` (prix de revient).

Valeur : celle donnée par la plateforme quand elle la donne (Coinbase), sinon une monnaie au
change du jour ; une crypto à son cours du jour (CoinGecko, sinon la
clôture Binance déposée avec l'opération) ; un stablecoin en dollar faute de cours. Les deux
côtés d'un échange prennent la valeur du côté le plus sûr (monnaie, puis stablecoin) : un
échange ne crée ni ne détruit de valeur, seuls ses frais coûtent. Un dépôt ou un retrait de
crypto relié à l'autre côté sur un autre de mes comptes (`links`) en prend la valeur. Sans
cours, l'opération attend (`missing_price`) et repasse quand les cours arrivent.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal, localcontext

from sqlalchemy import Connection, text

from hub.domains.finance.patrimoine.app import assets, links
from hub.domains.finance.patrimoine.model import instruments
from hub.domains.finance.patrimoine.model.instruments import Result
from hub.domains.finance.registre.app import catalog, ledger
from hub.domains.finance.registre.app.opening import open_account
from hub.domains.finance.sources.app import ibkr_writer
from hub.domains.finance.sources.infra.operations import KINDS, STABLE, Leg, Operation
from hub.kernel import canonical
from hub.kernel.money import DECIMAL_CONTEXT, base_currency


def open_empty(conn: Connection, account: catalog.Account, first: str) -> None:
    """Ouvre à zéro, la veille de sa première opération, un compte encore sans écriture."""
    if conn.execute(
        text("SELECT 1 FROM entries WHERE account_id = :a LIMIT 1"), {"a": account.id}
    ).first():
        return
    day = (date.fromisoformat(first) - timedelta(days=1)).isoformat()
    open_account(conn, account.id, day, 0, account.currency)


def _code(leg: Leg) -> tuple[str, str]:
    """(code, libellé) d'une jambe."""
    s = leg.symbol
    if leg.role == "deposit":
        return "EXCHANGE/DEPOSIT", f"Dépôt {s}"
    if leg.role == "withdrawal":
        return "EXCHANGE/WITHDRAWAL", f"Retrait {s}"
    if leg.role == "trade":
        if leg.quantity > 0:
            return "EXCHANGE/TRADE/BUY", f"Achat {s}"
        return "EXCHANGE/TRADE/SELL", f"Vente {s}"
    if leg.role == "income":
        return "EXCHANGE/INCOME", f"{s}"
    return "EXCHANGE/FEE", f"Frais {s}"


class Journal:
    """Écritures des opérations d'un fichier : un écrivain, le change, les comptes ouverts."""

    def __init__(self, conn: Connection, import_id: str) -> None:
        from hub.domains.finance.patrimoine.app import valuation

        self.conn = conn
        self.import_id = import_id
        self.fx = valuation.FxTable(conn)
        self.writer = ibkr_writer.Writer(
            conn, import_id, "exchange", Result(), namespace="exchange"
        )
        self.opened: set[str] = set()

    def value(self, leg: Leg, on: str) -> int | None:
        if leg.value is not None:
            got = self.fx.convert(leg.value, leg.value_currency, on)
            return None if got is None else (got if leg.quantity > 0 else -got)
        if leg.fiat:
            return self.fx.convert(leg.quantity, leg.symbol, on)
        known = assets.price_at(self.conn, instruments.crypto_key(leg.symbol), on)
        if known is not None:
            with localcontext(DECIMAL_CONTEXT):
                return self.fx.convert(leg.quantity * known[0], known[1], on)
        if leg.symbol in STABLE:
            return self.fx.convert(leg.quantity, "USD", on)
        return None

    def _trade_values(self, op: Operation, values: list[int | None]) -> None:
        """Un achat contre une vente : les deux à la valeur du côté le plus sûr."""
        trade = [i for i, leg in enumerate(op.legs) if leg.role == "trade"]
        bought = [i for i in trade if op.legs[i].quantity > 0]
        sold = [i for i in trade if op.legs[i].quantity < 0]
        if len(bought) != 1 or len(sold) != 1:
            return

        def rank(i: int) -> int:
            leg = op.legs[i]
            return 0 if leg.fiat else 1 if leg.symbol in STABLE else 2

        ref = min((bought[0], sold[0]), key=rank)
        if values[ref] is None:
            return
        v = abs(int(values[ref] or 0))
        values[bought[0]], values[sold[0]] = v, -v

    def apply(self, op: Operation, first: str) -> Result:
        result = Result()
        account = catalog.account_by_ref(self.conn, op.account)
        if account is None:
            return result.review("unknown_account")
        result.account_id = account.id
        if account.kind != "crypto" or account.currency != base_currency():
            return result.review("currency_mismatch")
        if account.id not in self.opened:
            self.opened.add(account.id)
            open_empty(self.conn, account, first)
        values = [self.value(leg, op.on_date) for leg in op.legs]
        self._trade_values(op, values)
        details: list[dict[str, str | int]] = []
        for i, leg in enumerate(op.legs):
            detail: dict[str, str | int] = {
                "quantity": instruments.qty_text(leg.quantity),
                "currency": leg.symbol,
            }
            for k in ("txid", "address", "network"):
                if getattr(op, k) and leg.role in ("deposit", "withdrawal"):
                    detail[k] = getattr(op, k)
            if leg.role in ("deposit", "withdrawal") and not leg.fiat:
                peer = links.counterpart(
                    self.conn, op.account, leg.symbol, op.on_date, leg.quantity, op.txid
                )
                if peer:
                    detail["peer"] = peer[0]
                    values[i] = -peer[1]
            details.append(detail)
        if any(v is None for v in values):
            return result.review("missing_price")
        self.writer.result = result
        name = KINDS[op.kind]
        for i, (leg, amount, detail) in enumerate(zip(op.legs, values, details, strict=True)):
            if not amount:
                continue
            code, label = _code(leg)
            if leg.role == "income":
                label = f"{name} {leg.symbol}"
            self.writer.entry(
                account,
                f"{op.id}|{op.account}|{i}",
                op.on_date,
                int(amount),
                code,
                label,
                counterparty=account.institution or account.name,
                remittance=f"{instruments.qty_text(leg.quantity)} {leg.symbol}",
                fx_json=canonical.dumps(detail),
            )
        self._trades(account, op, values)
        return result

    def _trades(self, account: catalog.Account, op: Operation, values: list[int | None]) -> None:
        """Mouvement de parts par crypto (pas pour une monnaie en attente)."""
        moved: dict[str, tuple[Decimal, int]] = defaultdict(lambda: (Decimal(0), 0))
        for leg, v in zip(op.legs, values, strict=True):
            if not leg.fiat:
                q, a = moved[leg.symbol]
                moved[leg.symbol] = (q + leg.quantity, a + int(v or 0))
        for symbol, (quantity, amount) in sorted(moved.items()):
            if not quantity:
                continue
            key = ledger.dedup_hash(f"exchange|{op.account}|{op.id}|{symbol}|trade")
            if self.conn.execute(
                text("SELECT 1 FROM trades WHERE dedup_key = :k"), {"k": key}
            ).first():
                continue
            instrument = instruments.crypto_key(symbol)
            assets.upsert_instrument(self.conn, instrument, None, kind="crypto", symbol=symbol)
            ledger.append(
                self.conn,
                "trades",
                {
                    "account_id": account.id,
                    "trade_date": op.on_date,
                    "isin": instrument,
                    "quantity": instruments.qty_text(quantity),
                    "amount_minor": amount,
                    "currency": account.currency,
                    "dedup_key": key,
                    "import_id": self.import_id,
                    "created_at": self.writer.created,
                },
            )
