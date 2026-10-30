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

from decimal import Decimal

from sqlalchemy import Connection, text

from hub.domains.finance.patrimoine.app import assets
from hub.domains.finance.patrimoine.model import instruments
from hub.domains.finance.patrimoine.model.instruments import Result
from hub.domains.finance.registre.app import catalog, ledger
from hub.domains.finance.registre.app.opening import open_account
from hub.domains.finance.sources.app.ibkr_writer import (
    Writer,
    _base_amount,
    _day_before,
    _ensure_cash,
    _minor,
)
from hub.domains.finance.sources.infra.ibkr_flex import (
    LABELS,
    OBSERVATIONS,
    Statement,
    titles_ref,
)
from hub.kernel import canonical
from hub.kernel.ids import urn
from hub.kernel.money import base_currency

# --- lecture --------------------------------------------------------------------------------


# --- écriture -------------------------------------------------------------------------------


def apply_statement(conn: Connection, import_id: str, st: Statement) -> Result:
    result = Result()
    titles = catalog.account_by_ref(conn, titles_ref(st.account))
    if titles is None:
        return result.review("unknown_account")
    result.account_id = titles.id
    if st.base_currency and st.base_currency != titles.currency:
        return result.review("currency_mismatch")
    unknown = sorted(c for c in st.currencies if not instruments.known_currency(c))
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
            open_account(
                conn, target.id, opening_day, _minor(amount, target.currency), target.currency
            )

    w = Writer(conn, import_id, st.account, result)
    for t in st.trades:
        side = "BUY" if t.quantity > 0 else "SELL"
        if t.category == "CASH":
            left, right = t.symbol.split(".")
            fx = canonical.dumps({"pair": t.symbol, "rate": instruments.price_text(t.price)})
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
                        "quantity": instruments.qty_text(t.quantity),
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
            if not instruments.known_currency(p.currency):
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
        if r.quote == base_currency() and instruments.known_currency(r.base):
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
