"""Positions et chiffres clés (ticket L2-02, lot 6) : les positions valorisées avec leur prix de
revient, et les chiffres clés du mois (patrimoine, épargne, flux, pilier 3a)."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal, localcontext
from typing import Any

from sqlalchemy import Connection, text

from hub.domains.finance.classement.app.insights import (
    expense_budget,
    last_clbds,
    lines_for,
    pillar3a_year,
    stale_accounts,
    to_categorize,
)
from hub.domains.finance.classement.app.totals import Totals
from hub.domains.finance.patrimoine.app import transfers, valuation
from hub.domains.finance.registre.model.amounts import (
    as_of,
    days_left,
    in_base,
    month_bounds,
    previous_months,
    ratio,
)
from hub.kernel.money import DECIMAL_CONTEXT, Money, base_currency, quantize

QTY_QUANTUM = Decimal("1e-12")  # quantités crypto des relevés, arrondies à 12 décimales


def holdings(conn: Connection, on_date: str) -> dict[str, Any]:
    """Positions des comptes de titres à une date : parts, dernier cours, valeur, prix de
    revient (coût moyen des achats, ou celui du dernier rapport) et poids."""
    positions = valuation.Positions(conn)
    names = {
        r[0]: (r[1], r[2], r[3])
        for r in conn.execute(text("SELECT isin, name, asset_class, sub_class FROM instruments"))
    }
    rows = conn.execute(text("SELECT id, name, kind FROM accounts WHERE kind != 'cash'"))
    accts, crypto = {}, set()
    for account_id, name, kind in rows:
        accts[account_id] = name
        if kind == "crypto":
            crypto.add(account_id)
    kinds = {r[0]: r[1] for r in conn.execute(text("SELECT isin, kind FROM instruments"))}
    lines = [
        line
        for account_id in sorted(positions.accounts)
        for line in positions.lines(account_id, on_date)
    ]
    total = sum(x.value for x in lines)
    items = []
    for x in lines:
        cost = _cost(conn, x.account_id, x.isin, x.quantity, on_date)
        if cost is None and x.account_id in crypto:
            # portefeuille sans opérations au registre : coût à l'arrivée
            cost = _arrival_cost(positions, x.account_id, x.isin, x.quantity, on_date)
        name, asset_class, sub_class = names.get(x.isin, (x.isin, None, None))
        items.append(
            {
                "account_id": x.account_id,
                "account": accts.get(x.account_id),
                "isin": x.isin,
                "name": name,
                "asset_class": asset_class,
                "sub_class": sub_class,
                "quantity": str(x.quantity),
                "price": str(x.price) if x.price is not None else None,
                "price_currency": x.currency,
                "kind": kinds.get(x.isin, "other"),
                "price_date": x.price_date,
                "value": in_base(x.value),
                "cost": in_base(cost) if cost is not None else None,
                "gain": in_base(x.value - cost) if cost is not None and x.price else None,
                "weight": ratio(x.value, total),
            }
        )
    costs = [i["cost"]["minor"] for i in items if i["cost"] is not None]
    return {
        "on_date": on_date,
        "currency": base_currency(),
        "items": items,
        "value": in_base(total),
        "cost": in_base(sum(costs)) if len(costs) == len(items) else None,
        "missing_prices": sorted({x.isin for x in lines if x.price is None}),
        "crypto": _crypto(
            conn, positions.fx, [x for x in lines if x.account_id in crypto], on_date
        ),
    }


def _arrival_cost(
    positions: valuation.Positions, account_id: str, isin: str, quantity: Decimal, on_date: str
) -> int | None:
    """Prix de revient d'une crypto sans achats connus (portefeuille, plateforme) : chaque hausse
    de quantité d'un relevé au suivant coûte sa valeur en CHF ce jour-là ; une baisse retire sa
    part du coût. Le gain se mesure donc depuis l'arrivée sur le portefeuille."""
    with localcontext(DECIMAL_CONTEXT):
        held, cost = Decimal(0), Decimal(0)
        for d, snapshot in positions.reports.get(account_id, []):
            if d > on_date:
                break
            q = snapshot[isin][0] if isin in snapshot else Decimal(0)
            if q > held:
                known = positions.price(isin, d)
                added = positions.fx.convert((q - held) * known[1], known[2], d) if known else None
                if added is None:
                    return None
                cost += added
            elif q < held:
                cost -= cost * (held - q) / held
            held = q
        return int(quantize(cost, 0)) if held == quantity else None


def _crypto(
    conn: Connection, fx: valuation.FxTable, lines: list[valuation.Line], on_date: str
) -> dict[str, Any] | None:
    """Performance globale des cryptos : investi = paiements nets de la catégorie « Crypto »
    (virements vers SwissBorg, Binance…, moins ce qui en revient), en CHF au change du jour du
    paiement ; résultat = valeur des portefeuilles moins investi. Ce qui attend chez une
    plateforme sans relevé compte comme investi sans valeur."""
    invested = 0
    rows = conn.execute(
        text(
            f"SELECT e.booking_date, e.amount_minor, e.currency FROM entries e "
            f"{valuation.CATEGORY_JOIN} WHERE vc.category_id = :c AND e.booking_date <= :d"
        ),
        {"c": valuation.CRYPTO_PURCHASE, "d": on_date},
    )
    for booked, amount, currency in rows:
        chf = fx.to_base(-int(amount), str(currency), str(booked))
        if chf is None:
            return None
        invested += chf
    if not invested and not lines:
        return None
    value = sum(x.value for x in lines)
    return {
        "invested": in_base(invested),
        "value": in_base(value),
        "result": in_base(value - invested),
        "missing_prices": any(x.price is None for x in lines),
    }


def _cost(
    conn: Connection, account_id: str, isin: str, quantity: Decimal, on_date: str
) -> int | None:
    """Coût moyen : un achat ajoute son montant, une vente retire sa part du coût. Si les avis
    ne rendent pas compte de toutes les parts (historique partiel), le prix de revient du
    dernier rapport, s'il est en CHF (il est dans la devise du fonds)."""
    with localcontext(DECIMAL_CONTEXT):
        held, cost = Decimal(0), Decimal(0)
        for qty, amount in conn.execute(
            text(
                "SELECT quantity, amount_minor FROM trades WHERE account_id = :a AND isin = :i "
                "AND trade_date <= :d ORDER BY trade_date, seq"
            ),
            {"a": account_id, "i": isin, "d": on_date},
        ):
            q = Decimal(qty)
            if q > 0:
                cost += Decimal(amount)
            elif held > 0:
                cost -= cost * (-q) / held
            held += q
        # une crypto peut porter plus de décimales que son relevé (arrondi à 12)
        if held.quantize(QTY_QUANTUM) == quantity.quantize(QTY_QUANTUM) and held:
            return int(quantize(cost, 0))
        row = conn.execute(
            text(
                "SELECT h.quantity, h.cost_price, n.currency FROM holdings h JOIN instruments n "
                "ON n.isin = h.isin WHERE h.account_id = :a AND h.isin = :i AND h.on_date <= :d "
                "ORDER BY h.on_date DESC LIMIT 1"
            ),
            {"a": account_id, "i": isin, "d": on_date},
        ).first()
        if (
            row is None
            or row[1] is None
            or row[2] != base_currency()
            or Decimal(row[0]) != quantity
        ):
            return None
        return Money.from_decimal(Decimal(row[0]) * Decimal(row[1]), base_currency()).minor


def _change(now: int, then: int, since: date) -> dict[str, Any]:
    return {
        "since": since.isoformat(),
        "amount": in_base(now - then),
        "ratio": ratio(now - then, then),
    }


def kpis(
    conn: Connection,
    month: str,
    today: date,
    *,
    pillar3a: bool = True,
    pillar3a_cap: int | None = None,
) -> dict[str, Any]:
    at = as_of(month, today)
    start = date.fromisoformat(month_bounds(month)[0])
    now = valuation.value_at(conn, at.isoformat())
    m1 = valuation.value_at(conn, (start - timedelta(days=1)).isoformat())
    dec31 = date(at.year - 1, 12, 31)
    y0 = valuation.value_at(conn, dec31.isoformat())
    t = Totals.of(lines_for(conn, [month]))
    budget = expense_budget(conn, month)
    q = Totals.of(lines_for(conn, previous_months(month, 3)))
    six = previous_months(month, 6)
    with_data = [m for m in six if lines_for(conn, [m])]
    avg = Totals.of(lines_for(conn, six)).expenses // len(with_data) if with_data else 0
    clbds = [d for _a, d in last_clbds(conn) if d]
    return {
        "month": month,
        "as_of": at.isoformat(),
        "currency": base_currency(),
        "net_worth": in_base(now.net_worth),
        "envelopes": {k: in_base(v) for k, v in now.by_envelope.items()},
        "change_1m": _change(now.net_worth, m1.net_worth, start - timedelta(days=1)),
        "change_ytd": _change(now.net_worth, y0.net_worth, dec31),
        "deposits_ytd": in_base(now.deposits - y0.deposits),
        "market_ytd": in_base((now.net_worth - now.deposits) - (y0.net_worth - y0.deposits)),
        "income": in_base(t.income),
        "expenses": in_base(t.expenses),
        "savings": in_base(t.savings),
        "savings_rate": ratio(t.savings, t.income),
        "budget": in_base(budget) if budget is not None else None,
        "budget_used": ratio(t.expenses, budget) if budget else None,
        "rest_to_live": in_base(budget - t.expenses) if budget is not None else None,
        "days_left": days_left(month, today),
        "liquid": in_base(now.liquid),
        "months_covered": ratio(now.liquid, avg, 1) if avg > 0 else None,
        "savings_rate_3m": ratio(q.savings, q.income),
        "stale_accounts": stale_accounts(conn, today),
        "to_categorize": to_categorize(conn),
        "unmatched_transfers": transfers.summary(conn, detailed=False)["unmatched"],
        "pillar3a": pillar3a_year(conn, at.year, at, pillar3a_cap) if pillar3a else None,
        "last_statement": max(clbds) if clbds else None,
        "missing_fx": now.missing_fx,
        "missing_prices": now.missing_prices,
    }
