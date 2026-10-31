"""Cours du marché et soldes des portefeuilles crypto (lot 6) : fichier `hub.market.v1` déposé
par le collecteur « market ».

Le fichier porte ces listes, chacune facultative :

- `fx` : cours de change de la BCE (1 devise = rate dans la devise de base), vers `fx_rates` ;
- `prices` : cours quotidiens (cryptos, titres cotés), vers `prices` ;
- `balances` : solde d'un portefeuille crypto relevé sur la chaîne (adresses publiques), qui
  devient un relevé de positions du compte `crypto:<nom>` à cette date ; un relevé de plus le
  même jour (« Actualiser ») remplace celui du matin pour ce qui a bougé, une crypto sortie du
  relevé y passe à zéro ;
- `transactions` : une transaction du portefeuille sur la chaîne (net reçu ou envoyé, frais
  payés), qui devient une opération au registre du compte, en devise de base, et un mouvement
  de parts. Un envoi ou une arrivée relié à l'autre côté sur un autre de mes comptes (même
  txId, sinon même quantité, à quelques jours près : `links`) en prend la valeur : c'est un
  virement entre mes comptes ;
- `operations` : une opération d'une plateforme (dépôt, retrait, échange, récompense), au
  registre de son compte (`exchange`).

Relevé 0 : les cours ; puis un relevé par portefeuille, un par transaction, un par opération. Un
portefeuille dont le compte n'est pas encore déclaré (`hub finance crypto add-wallet`) attend,
le reste s'applique.
Montants et cours sont des textes décimaux : jamais de flottant.
"""

from __future__ import annotations

from decimal import Decimal, localcontext

from sqlalchemy import Connection, text

from hub.domains.finance.patrimoine.app import assets, links
from hub.domains.finance.patrimoine.model import instruments
from hub.domains.finance.patrimoine.model.instruments import Result
from hub.domains.finance.registre.app import catalog, ledger
from hub.domains.finance.sources.app import exchange, ibkr_writer
from hub.domains.finance.sources.infra import operations
from hub.domains.finance.sources.infra.market_file import Balance, MarketFile, Transaction
from hub.kernel import canonical
from hub.kernel.ids import urn
from hub.kernel.money import DECIMAL_CONTEXT, base_currency


def _apply_rates(conn: Connection, import_id: str, doc: MarketFile) -> Result:
    result = Result()
    for f in doc.fx:
        if not (instruments.known_currency(f.base) and instruments.known_currency(f.quote)):
            continue
        if assets.add_fx(conn, f.on_date, f.base, f.quote, f.rate, f.source):
            result.new += 1
        else:
            result.duplicates += 1
    for p in doc.prices:
        if not instruments.known_currency(p.currency) or p.price <= 0:
            result.reasons.add("unknown_currency")
            continue
        assets.upsert_instrument(
            conn,
            p.key,
            p.name,
            kind=p.kind,
            currency=p.currency,
            symbol=instruments.symbol_of(p.key),
        )
        if assets.add_price(conn, p.key, p.on_date, p.price, p.currency, p.source, import_id):
            result.new += 1
        else:
            result.duplicates += 1
    return result


price_at = assets.price_at


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
    assets.upsert_instrument(conn, b.key, None, kind="crypto", symbol=instruments.symbol_of(b.key))
    if assets.add_holding(
        conn, account.id, b.on_date, b.key, b.quantity, value, ccy, import_id, intraday=True
    ):
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


def _vanished(
    conn: Connection, import_id: str, doc: MarketFile, applied: dict[tuple[str, str], set[str]]
) -> None:
    """Un compte relevé en entier ce jour-là (toutes ses lignes appliquées) : une crypto du
    relevé précédent du même jour qui n'y est plus passe à zéro."""
    listed: dict[tuple[str, str], set[str]] = {}
    for b in doc.balances:
        listed.setdefault((b.account, b.on_date), set()).add(b.key)
    for (ref, on_date), keys in sorted(applied.items()):
        account = catalog.account_by_ref(conn, ref)
        if account is None or keys != listed[(ref, on_date)]:
            continue
        held = assets.day_holdings(conn, account.id, on_date)
        gone = [k for k, q in sorted(held.items()) if k not in keys and Decimal(q) != 0]
        for key in gone:
            assets.add_holding(
                conn,
                account.id,
                on_date,
                key,
                Decimal(0),
                Decimal(0),
                account.currency,
                import_id,
                intraday=True,
            )
        if gone:
            ledger.append_event(
                conn,
                "holdings.recorded",
                urn("finance", "account", account.id),
                {"import_id": import_id, "count": len(gone)},
            )


class _Chain:
    """Écritures des transactions d'un fichier : un écrivain, le change, les comptes ouverts."""

    def __init__(self, conn: Connection, import_id: str) -> None:
        from hub.domains.finance.patrimoine.app import valuation

        self.conn = conn
        self.import_id = import_id
        self.fx = valuation.FxTable(conn)
        self.writer = ibkr_writer.Writer(conn, import_id, "chain", Result(), namespace="chain")
        self.opened: set[str] = set()

    def value(self, t: Transaction, quantity: Decimal) -> int | None:
        known = price_at(self.conn, t.key, t.on_date)
        if known is None:
            if t.symbol in operations.STABLE:  # stablecoin sans cours : le dollar
                return self.fx.convert(quantity, "USD", t.on_date)
            return None
        with localcontext(DECIMAL_CONTEXT):
            return self.fx.convert(quantity * known[0], known[1], t.on_date)

    def open(self, account: catalog.Account, first: str) -> None:
        if account.id not in self.opened:
            self.opened.add(account.id)
            exchange.open_empty(self.conn, account, first)

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
        detail: dict[str, str | int] = {"txid": t.txid, "currency": t.symbol}
        sent = t.quantity + t.fee  # hors frais : ce qui quitte le portefeuille (négatif)
        moved = t.quantity if t.quantity > 0 else sent
        peer = links.counterpart(self.conn, t.account, t.symbol, t.on_date, moved, t.txid)
        if peer:
            detail["peer"] = peer[0]
        if t.quantity > 0:
            amount = -peer[1] if peer else self.value(t, t.quantity)
            legs = [("receive", "CRYPTO/RECEIVE", f"Réception {t.symbol}", t.quantity, amount)]
            cost = amount
        else:
            fee = self.value(t, -t.fee) if t.fee else 0
            amount = -peer[1] if peer else self.value(t, sent)
            legs = [
                ("send", "CRYPTO/SEND", f"Envoi {t.symbol}", sent, amount),
                ("fee", "CRYPTO/FEE", f"Frais de réseau {t.symbol}", -t.fee, fee),
            ]
            cost = None if amount is None or fee is None else amount + fee
        if cost is None or any(v is None for *_x, v in legs):
            return result.review("missing_price")
        for leg, code, label, qty, amount in legs:
            if amount:
                fx = canonical.dumps({**detail, "quantity": instruments.qty_text(qty)})
                self.writer.entry(
                    account,
                    f"{t.txid}|{leg}" if t.symbol == "BTC" else f"{t.txid}|{t.symbol}|{leg}",
                    t.on_date,
                    int(amount),
                    code,
                    label,
                    remittance=f"{instruments.qty_text(qty)} {t.symbol}",
                    fx_json=fx,
                )
        # une transaction Ethereum porte l'ETH (le gaz) et un jeton : une clé par crypto
        part = t.txid if t.symbol == "BTC" else f"{t.txid}|{t.symbol}"
        trade_key = ledger.dedup_hash(f"chain|{t.account}|{part}|trade")
        if (
            t.quantity
            and not self.conn.execute(
                text("SELECT 1 FROM trades WHERE dedup_key = :k"), {"k": trade_key}
            ).first()
        ):
            assets.upsert_instrument(
                self.conn, t.key, None, kind="crypto", symbol=instruments.symbol_of(t.key)
            )
            ledger.append(
                self.conn,
                "trades",
                {
                    "account_id": account.id,
                    "trade_date": t.on_date,
                    "isin": t.key,
                    "quantity": instruments.qty_text(t.quantity),
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
    applied: dict[tuple[str, str], set[str]] = {}
    for i, b in enumerate(doc.balances, start=1):
        if indexes is None or i in indexes:
            result = apply_balance(conn, import_id, b)
            out.append((i, result))
            if result.status == "applied":
                applied.setdefault((b.account, b.on_date), set()).add(b.key)
    _vanished(conn, import_id, doc, applied)
    if doc.transactions:
        chain = _Chain(conn, import_id)
        firsts: dict[str, str] = {}
        for t in doc.transactions:
            firsts.setdefault(t.account, t.on_date)
        for i, t in enumerate(doc.transactions, start=len(doc.balances) + 1):
            if indexes is None or i in indexes:
                out.append((i, chain.apply(t, firsts[t.account])))
        _appended(conn, import_id, chain.writer.touched)
    if doc.operations:
        journal = exchange.Journal(conn, import_id)
        starts: dict[str, str] = {}
        for o in doc.operations:
            starts.setdefault(o.account, o.on_date)
        first = len(doc.balances) + len(doc.transactions) + 1
        for i, o in enumerate(doc.operations, start=first):
            if indexes is None or i in indexes:
                out.append((i, journal.apply(o, starts[o.account])))
        _appended(conn, import_id, journal.writer.touched)
    return out


def _appended(conn: Connection, import_id: str, touched: dict[str, int]) -> None:
    for account_id, count in sorted(touched.items()):
        ledger.append_event(
            conn,
            "entries.appended",
            urn("finance", "account", account_id),
            {"import_id": import_id, "count": count},
        )
