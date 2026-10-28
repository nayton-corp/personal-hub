"""Écriture des documents VIAC au registre (ticket L4-05), dans la transaction de l'appelant.

Chaque portefeuille a deux comptes de prévoyance : les liquidités 3a (`viac:<n°>:cash`), où
passent versements, dividendes, intérêts et commissions, et les titres (`viac:<n°>:titres`),
valorisés par leurs positions. Un achat débite les liquidités et crédite les titres du même
montant (et l'inverse pour une vente) : seuls les versements et retraits sont des apports,
tout le reste est du rendement ou un mouvement interne.

Un avis écrit ses écritures, sa ligne de `trades` et le cours qu'il donne. Un rapport écrit
les positions relevées, leurs cours et le solde du compte 3a (point de contrôle), et compare :
liquidités du registre et parts issues des avis, contre ce que VIAC annonce. Ces écarts sont
signalés, jamais bloquants : le rapport est une observation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, localcontext

from sqlalchemy import Connection, text

from hub.core.clock import now_iso
from hub.core.ids import urn
from hub.core.money import DECIMAL_CONTEXT, Money
from hub.domains.finance import catalog, ledger, rules
from hub.domains.finance.viac.models import CASH_SIGN, LABEL, TX_CODE, Notice, PortfolioReport

CCY = "CHF"
PRICE_PLACES = 8


def cash_ref(portfolio: str) -> str:
    return f"viac:{portfolio}:cash"


def titles_ref(portfolio: str) -> str:
    return f"viac:{portfolio}:titres"


def qty_text(value: Decimal) -> str:
    """Quantité exacte, sans exposant ni zéros superflus : '12.345', '-2', '0'."""
    out = format(value.normalize(), "f")
    return "0" if out in ("-0", "") else out


@dataclass
class Outcome:
    """Résultat d'un document (avis) ou d'un portefeuille (rapport)."""

    status: str  # 'applied' | 'needs_review'
    reasons: list[str] = field(default_factory=list)
    new: int = 0
    duplicates: int = 0
    cash_id: str | None = None
    titles_id: str | None = None


def _accounts(
    conn: Connection, portfolio: str
) -> tuple[catalog.Account | None, catalog.Account | None]:
    return (
        catalog.account_by_ref(conn, cash_ref(portfolio)),
        catalog.account_by_ref(conn, titles_ref(portfolio)),
    )


def _opening(conn: Connection, account_id: str) -> str | None:
    row = conn.execute(
        text("SELECT booking_date FROM entries WHERE account_id = :a AND kind = 'opening'"),
        {"a": account_id},
    ).first()
    return str(row[0]) if row else None


def _known(conn: Connection, table: str, key: str) -> bool:
    return (
        conn.execute(text(f"SELECT 1 FROM {table} WHERE dedup_key = :k"), {"k": key}).first()  # noqa: S608
        is not None
    )


def minor(amount: Decimal) -> int:
    return Money.from_decimal(amount, CCY).minor


def unit_price(value_minor: int, quantity: Decimal) -> str:
    """Cours unitaire en CHF tiré d'un montant et d'un nombre de parts."""
    with localcontext(DECIMAL_CONTEXT):
        price = Money(value_minor, CCY).to_decimal() / quantity
        return qty_text(price.quantize(Decimal(1).scaleb(-PRICE_PLACES)))


def notice_price(n: Notice) -> str:
    """Cours d'un avis : le cours imprimé quand il est en CHF. Le montant divisé par les parts
    s'en écarte de quelques pour cent sur les petits achats, dont VIAC arrondit les parts à
    2 décimales ; il ne sert qu'en devise étrangère, faute de taux sur l'avis."""
    if n.price is not None and n.price_currency == CCY and n.price > 0:
        return qty_text(n.price.quantize(Decimal(1).scaleb(-PRICE_PLACES)))
    assert n.quantity is not None  # noqa: S101 - appelé pour une opération avec parts
    return unit_price(minor(n.amount), n.quantity)


def upsert_instrument(
    conn: Connection,
    isin: str,
    name: str,
    *,
    asset_class: str | None = None,
    sub_class: str | None = None,
    currency: str | None = None,
    overwrite: bool = False,
) -> None:
    """Le nom d'un fonds est une métadonnée : le rapport, plus complet, remplace l'avis."""
    found = conn.execute(text("SELECT 1 FROM instruments WHERE isin = :i"), {"i": isin}).first()
    params = {
        "i": isin,
        "n": name,
        "a": asset_class,
        "s": sub_class,
        "c": currency,
        "at": now_iso(),
    }
    if found is None:
        conn.execute(
            text(
                "INSERT INTO instruments (isin, name, asset_class, sub_class, currency, "
                "updated_at) VALUES (:i, :n, :a, :s, :c, :at)"
            ),
            params,
        )
    elif overwrite:
        conn.execute(
            text(
                "UPDATE instruments SET name = :n, asset_class = :a, sub_class = :s, "
                "currency = :c, updated_at = :at WHERE isin = :i"
            ),
            params,
        )


def _price(conn: Connection, isin: str, on: str, price: str, source: str, import_id: str) -> None:
    found = conn.execute(
        text("SELECT 1 FROM prices WHERE isin = :i AND on_date = :d AND source = :s"),
        {"i": isin, "d": on, "s": source},
    ).first()
    if found is None:
        ledger.append(
            conn,
            "prices",
            {
                "isin": isin,
                "on_date": on,
                "price": price,
                "currency": CCY,
                "source": source,
                "import_id": import_id,
                "created_at": now_iso(),
            },
        )


# --- avis ------------------------------------------------------------------------------------


def notice_key(n: Notice, side: str) -> str:
    parts = [
        "viac",
        n.portfolio,
        side,
        n.kind,
        n.value_date,
        n.isin or "",
        str(minor(n.amount)),
        qty_text(n.quantity) if n.quantity is not None else "",
    ]
    return ledger.dedup_hash("|".join(parts) + "|0")


def apply_notice(conn: Connection, import_id: str, n: Notice) -> Outcome:
    cash, titles = _accounts(conn, n.portfolio)
    if cash is None or titles is None:
        return Outcome("needs_review", ["unknown_account"])
    out = Outcome("applied", cash_id=cash.id, titles_id=titles.id)
    reasons = []
    for a in (cash, titles):
        opened = _opening(conn, a.id)
        if opened is None:
            reasons.append("no_opening")
        elif n.value_date <= opened:
            reasons.append("before_opening")
    if reasons:
        out.status, out.reasons = "needs_review", sorted(set(reasons))
        return out

    amount = CASH_SIGN[n.kind] * minor(n.amount)
    sides = [("cash", cash, amount)]
    if n.is_trade:
        sides.append(("titres", titles, -amount))
    ruleset = rules.load(conn)
    created = now_iso()
    for side, account, value in sides:
        key = notice_key(n, side)
        if _known(conn, "entries", key):
            out.duplicates += 1
            continue
        entry = ledger.NewEntry(
            account_id=account.id,
            booking_date=n.value_date,
            value_date=n.value_date,
            amount_minor=value,
            currency=CCY,
            counterparty=n.fund,
            label=LABEL[n.kind],
            remittance=n.detail,
            bank_tx_code=TX_CODE[n.kind],
            dedup_key=key,
            import_id=import_id,
        )
        seq, _ = ledger.append_entry(conn, entry, created)
        target = rules.Target(
            value,
            ledger.search_text(entry.counterparty, entry.label, entry.remittance),
            None,
            entry.bank_tx_code,
            None,
        )
        won = ruleset.winner(target)
        if won is not None:
            rules.categorize(conn, seq, won, proposal_id=None, created_at=created)
        out.new += 1
        ledger.append_event(
            conn,
            "entries.appended",
            urn("finance", "account", account.id),
            {"import_id": import_id, "count": 1},
        )
    if n.is_trade and n.isin and n.quantity is not None:
        sign = 1 if n.kind == "buy" else -1
        key = ledger.dedup_hash(
            f"viac|{n.portfolio}|trade|{n.value_date}|{n.isin}|{qty_text(n.quantity)}|"
            f"{minor(n.amount)}|0"
        )
        if not _known(conn, "trades", key):
            ledger.append(
                conn,
                "trades",
                {
                    "account_id": titles.id,
                    "trade_date": n.value_date,
                    "isin": n.isin,
                    "quantity": qty_text(sign * n.quantity),
                    "amount_minor": sign * minor(n.amount),
                    "currency": CCY,
                    "dedup_key": key,
                    "import_id": import_id,
                    "created_at": created,
                },
            )
        upsert_instrument(conn, n.isin, n.fund or n.isin)
        _price(
            conn,
            n.isin,
            n.value_date,
            notice_price(n),
            "viac_notice",
            import_id,
        )
    return out


# --- rapport ---------------------------------------------------------------------------------


def traded_quantities(conn: Connection, account_id: str, until: str) -> dict[str, Decimal]:
    out: dict[str, Decimal] = {}
    rows = conn.execute(
        text("SELECT isin, quantity FROM trades WHERE account_id = :a AND trade_date <= :d"),
        {"a": account_id, "d": until},
    )
    with localcontext(DECIMAL_CONTEXT):
        for isin, quantity in rows:
            out[isin] = out.get(isin, Decimal(0)) + Decimal(quantity)
    return out


def apply_portfolio(conn: Connection, import_id: str, on: str, p: PortfolioReport) -> Outcome:
    cash, titles = _accounts(conn, p.number)
    if cash is None or titles is None:
        return Outcome("needs_review", ["unknown_account"])
    out = Outcome("applied", cash_id=cash.id, titles_id=titles.id)
    reasons: set[str] = set()
    created = now_iso()
    for pos in p.positions:
        upsert_instrument(
            conn,
            pos.isin,
            pos.name,
            asset_class=pos.category,
            sub_class=pos.sub_class,
            currency=pos.currency,
            overwrite=True,
        )
        exists = conn.execute(
            text("SELECT 1 FROM holdings WHERE account_id = :a AND on_date = :d AND isin = :i"),
            {"a": titles.id, "d": on, "i": pos.isin},
        ).first()
        if exists:
            out.duplicates += 1
            continue
        value = minor(pos.value)
        ledger.append(
            conn,
            "holdings",
            {
                "account_id": titles.id,
                "on_date": on,
                "isin": pos.isin,
                "quantity": qty_text(pos.quantity),
                "value_minor": value,
                "currency": CCY,
                "cost_price": qty_text(pos.cost_price),
                "import_id": import_id,
                "created_at": created,
            },
        )
        out.new += 1
        if pos.quantity > 0:
            _price(conn, pos.isin, on, unit_price(value, pos.quantity), "viac_report", import_id)

    # parts issues des avis contre parts relevées (si des avis existent pour ce compte)
    has_trades = conn.execute(
        text("SELECT 1 FROM trades WHERE account_id = :a LIMIT 1"), {"a": titles.id}
    ).first()
    if has_trades:
        traded = {k: v for k, v in traded_quantities(conn, titles.id, on).items() if v != 0}
        reported = {pos.isin: pos.quantity for pos in p.positions if pos.quantity != 0}
        if traded != reported:
            reasons.add("holdings_mismatch")

    if p.cash is not None:
        amount = minor(p.cash)
        known = conn.execute(
            text(
                "SELECT amount_minor FROM checkpoints WHERE account_id = :a AND on_date = :d "
                "AND kind = 'CLBD'"
            ),
            {"a": cash.id, "d": on},
        ).scalar_one_or_none()
        if known is None:
            ledger.append(
                conn,
                "checkpoints",
                {
                    "account_id": cash.id,
                    "on_date": on,
                    "kind": "CLBD",
                    "amount_minor": amount,
                    "import_id": import_id,
                },
            )
        elif known != amount:
            reasons.add("checkpoint_conflict")
        balance = conn.execute(
            text(
                "SELECT coalesce(sum(amount_minor), 0) FROM entries WHERE account_id = :a "
                "AND booking_date <= :d AND kind != 'correction'"
            ),
            {"a": cash.id, "d": on},
        ).scalar_one()
        if _opening(conn, cash.id) is not None and balance != amount:
            reasons.add("ledger_check_failed")
    if out.new:
        ledger.append_event(
            conn,
            "holdings.recorded",
            urn("finance", "account", titles.id),
            {"import_id": import_id, "count": out.new},
        )
    out.reasons = sorted(reasons)
    return out
