"""Chiffres de l'app (ticket L2-02) : les neuf calculs du dashboard prototype, côté serveur et
en centimes.

Le « mois en cours » vient toujours du paramètre `month` et « aujourd'hui » de l'appelant ;
rien n'est déduit des données. Le début d'année est le 31 décembre précédent. Les rapports
sont des décimales en texte (`"0.2534"`), jamais des flottants.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterator
from datetime import date, timedelta
from decimal import Decimal, localcontext
from typing import Any

from sqlalchemy import Connection, text

from hub.core.money import DECIMAL_CONTEXT, Money, base_currency, quantize
from hub.domains.finance import institutions, transfers, valuation
from hub.domains.finance.reads import (
    MIN_COUNT_FOR_AGGREGATES,
    OTHERS,
    UNCATEGORIZED,
    Line,
    Totals,
    _budget_accounts,
    _in,
    money,
    month_bounds,
    period_lines,
    shift_month,
)

STALE_DAYS = 45
EPARGNE_3A = "epargne-3a"
PENSION_DEPOSITS = institutions.like_any(
    "bank_tx_code", institutions.prefixes(pension_deposit=True)
)
# plafond du 3e pilier A pour un salarié affilié à une caisse de pension, en centimes ;
# une année absente prend le dernier plafond connu, `[finance] pillar3a_cap_minor` le remplace
PILLAR_3A_CAP = {2024: 705_600, 2025: 725_800, 2026: 725_800}
EXPENSE_GROUPS = ("fixed", "variable")
FLOW_GROUPS = ("fixed", "variable", "savings")
NAMES_EXTRA = {UNCATEGORIZED: "À catégoriser", OTHERS: "Autres"}


def in_base(minor: int) -> dict[str, Any]:
    """Montant de l'API dans la devise de base de l'instance."""
    return money(minor, base_currency())


class FutureMonth(ValueError):
    pass


# --- périodes ---------------------------------------------------------------------------------


def month_end(month: str) -> date:
    _, end = month_bounds(month)
    return date.fromisoformat(end) - timedelta(days=1)


def as_of(month: str, today: date) -> date:
    """Fin du mois, ou aujourd'hui pour le mois en cours ; un mois futur est refusé."""
    start, _ = month_bounds(month)
    if date.fromisoformat(start) > today:
        raise FutureMonth(month)
    return min(month_end(month), today)


def previous_months(month: str, n: int) -> list[str]:
    """Les `n` mois complets avant `month`, du plus ancien au plus récent."""
    return [shift_month(month, -k) for k in range(n, 0, -1)]


def period_months(month: str, period: str) -> list[str]:
    """`m` : le mois lui-même ; `q` : les trois mois complets qui le précèdent."""
    return [month] if period == "m" else previous_months(month, 3)


def span(months: list[str]) -> tuple[str, str]:
    return month_bounds(months[0])[0], month_bounds(months[-1])[1]


def ratio(num: int, den: int, places: int = 4) -> str | None:
    if den == 0:
        return None
    with localcontext(DECIMAL_CONTEXT):
        return str(quantize(Decimal(num) / Decimal(den), places))


def days_left(month: str, today: date) -> int:
    """Jours après aujourd'hui jusqu'à la fin du mois ; 0 pour un mois passé."""
    return max(0, (month_end(month) - today).days)


# --- briques ----------------------------------------------------------------------------------


def category_names(conn: Connection) -> dict[str, str]:
    names = {r[0]: r[1] for r in conn.execute(text("SELECT id, name FROM categories"))}
    return {**names, **NAMES_EXTRA}


def targets(conn: Connection, month: str) -> dict[str, int]:
    """Cible mensuelle en vigueur au début du mois, par catégorie (la dernière ligne gagne)."""
    rows = conn.execute(
        text(
            "SELECT b.category_id, b.monthly_minor FROM budgets b "
            "WHERE b.currency = :ccy AND b.seq = (SELECT max(seq) FROM budgets "
            "WHERE category_id = b.category_id AND valid_from <= :m)"
        ),
        {"m": f"{month}-01", "ccy": base_currency()},
    )
    return {r[0]: int(r[1]) for r in rows}


def category_groups(conn: Connection) -> dict[str, str]:
    return {r[0]: r[1] for r in conn.execute(text("SELECT id, grp FROM categories"))}


def expense_budget(conn: Connection, month: str) -> int | None:
    groups = category_groups(conn)
    found = {c: v for c, v in targets(conn, month).items() if groups.get(c) in EXPENSE_GROUPS}
    return sum(found.values()) if found else None


def lines_for(conn: Connection, months: list[str]) -> list[Line]:
    start, end = span(months)
    return period_lines(conn, start, end, base_currency())


def merge_small(items: list[dict[str, Any]], key: str = "total") -> list[dict[str, Any]]:
    """Portée aggregates : une catégorie de moins de 3 écritures rejoint « Autres »."""
    kept = [i for i in items if i["count"] >= MIN_COUNT_FOR_AGGREGATES]
    small = [i for i in items if i["count"] < MIN_COUNT_FOR_AGGREGATES]
    if not small:
        return kept
    other: dict[str, Any] = {
        "category": OTHERS,
        "name": NAMES_EXTRA[OTHERS],
        key: in_base(sum(i[key]["minor"] for i in small)),
        "count": sum(i["count"] for i in small),
    }
    for extra in ("group",):
        if extra in small[0]:
            other[extra] = small[0][extra] if len({i[extra] for i in small}) == 1 else "mixed"
    if "target" in small[0]:
        tg = [i["target"]["minor"] for i in small if i["target"]]
        other["target"] = in_base(sum(tg)) if tg else None
        other["ratio"] = ratio(other[key]["minor"], sum(tg)) if tg else None
        other["over"] = bool(tg) and other[key]["minor"] > sum(tg)
    return [*kept, other]


def totals_json(t: Totals) -> dict[str, Any]:
    return {
        "income": in_base(t.income),
        "expenses": in_base(t.expenses),
        "fixed": in_base(t.fixed),
        "variable": in_base(t.variable),
        "savings": in_base(t.savings),
        "invested": in_base(t.invested),
        "rate": ratio(t.savings, t.income),
    }


def _last_clbds(conn: Connection) -> list[tuple[str, str | None]]:
    rows = conn.execute(
        text(
            "SELECT a.id, (SELECT max(on_date) FROM checkpoints c WHERE c.account_id = a.id "
            "AND c.kind = 'CLBD') FROM accounts a WHERE a.kind = 'cash' AND a.closed_on IS NULL"
        )
    ).fetchall()
    return [(r[0], r[1]) for r in rows]


def stale_accounts(conn: Connection, today: date) -> int:
    limit = (today - timedelta(days=STALE_DAYS)).isoformat()
    return sum(1 for _a, d in _last_clbds(conn) if d is None or d < limit)


def to_categorize(conn: Connection) -> int:
    return int(
        conn.execute(
            text(
                "SELECT count(*) FROM entries e LEFT JOIN v_entry_category vc "
                "ON vc.entry_seq = e.seq WHERE vc.category_id IS NULL AND e.kind = 'movement' "
                # un côté de virement apparié n'attend pas de catégorie (lot 6)
                "AND e.seq NOT IN (SELECT debit_seq FROM transfer_links) "
                "AND e.seq NOT IN (SELECT credit_seq FROM transfer_links)"
            )
        ).scalar_one()
    )


def pillar3a_year(
    conn: Connection, year: int, until: date, cap: int | None = None
) -> dict[str, Any]:
    """Versements 3a de l'année : ceux que VIAC a reçus (avis de versement) ou, à défaut, les
    paiements catégorisés « épargne 3a » sur les comptes courants ; le plus grand des deux,
    pour qu'un historique VIAC incomplet ou une catégorie manquante ne sous-estime rien."""
    if cap is None:
        known = [y for y in PILLAR_3A_CAP if y <= year] or [min(PILLAR_3A_CAP)]
        cap = PILLAR_3A_CAP[max(known)]
    period = {"ccy": base_currency(), "s": f"{year}-01-01", "e": until.isoformat()}
    ids, params = _in("a", _budget_accounts(conn))
    from_bank = -int(
        conn.execute(
            text(
                "SELECT coalesce(sum(amount_minor), 0) FROM v_entry_allocation "
                f"WHERE category_id = :c AND account_id IN {ids} AND currency = :ccy "
                "AND booking_date >= :s AND booking_date <= :e"
            ),
            {**params, **period, "c": EPARGNE_3A},
        ).scalar_one()
    )
    at_viac = int(
        conn.execute(
            text(
                "SELECT coalesce(sum(amount_minor), 0) FROM entries "
                f"WHERE ({PENSION_DEPOSITS}) AND currency = :ccy "
                "AND booking_date >= :s AND booking_date <= :e"
            ),
            period,
        ).scalar_one()
    )
    paid = max(from_bank, at_viac)
    return {
        "year": year,
        "cap": in_base(cap),
        "paid": in_base(paid),
        "margin": in_base(max(0, cap - paid)),
        "source": "viac" if at_viac and at_viac >= from_bank else "bank",
    }


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
        if x.account_id in crypto:
            cost = _arrival_cost(positions, x.account_id, x.isin, x.quantity, on_date)
        else:
            cost = _cost(conn, x.account_id, x.isin, x.quantity, on_date)
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
        if held == quantity:
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


# --- routes -----------------------------------------------------------------------------------


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
    clbds = [d for _a, d in _last_clbds(conn) if d]
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


def flows(conn: Connection, month: str, *, aggregates_only: bool) -> dict[str, Any]:
    lines = lines_for(conn, [month])
    names = category_names(conn)
    t = Totals.of(lines)

    def items(group: str, sign: int) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = [
            {
                "category": x.category,
                "name": names.get(x.category, x.category),
                "total": in_base(sign * x.minor),
                "count": x.count,
            }
            for x in lines
            if x.group == group and x.minor != 0
        ]
        out.sort(key=lambda i: (-i["total"]["minor"], i["category"]))
        return merge_small(out) if aggregates_only else out

    groups = [
        {
            "group": g,
            "total": in_base(-sum(x.minor for x in lines if x.group == g)),
            "items": items(g, -1),
        }
        for g in FLOW_GROUPS
    ]
    return {
        "month": month,
        "currency": base_currency(),
        "income": in_base(t.income),
        "sources": items("income", 1),
        "groups": groups,
        "remainder": in_base(t.income - t.expenses - t.invested),
    }


def budget(
    conn: Connection, month: str, period: str, today: date, *, aggregates_only: bool
) -> dict[str, Any]:
    months = period_months(month, period)
    n = len(months)
    lines = lines_for(conn, months)
    names = category_names(conn)
    goal = targets(conn, months[-1])
    groups = category_groups(conn)
    spent: dict[str, tuple[str, int, int]] = {}
    for x in lines:
        if x.group in EXPENSE_GROUPS:
            g, minor, count = spent.get(x.category, (x.group, 0, 0))
            spent[x.category] = (g, minor - x.minor, count + x.count)
    for cat in goal:
        if groups.get(cat) in EXPENSE_GROUPS and cat not in spent:
            spent[cat] = (groups[cat], 0, 0)
    out: list[dict[str, Any]] = []
    for cat, (group, minor, count) in spent.items():
        target = goal[cat] * n if cat in goal else None
        out.append(
            {
                "category": cat,
                "name": names.get(cat, cat),
                "group": group,
                "spent": in_base(minor),
                "count": count,
                "target": in_base(target) if target is not None else None,
                "ratio": ratio(minor, target) if target else None,
                "over": target is not None and minor > target,
            }
        )
    out.sort(key=lambda i: (EXPENSE_GROUPS.index(i["group"]), -i["spent"]["minor"], i["category"]))
    if aggregates_only:
        out = merge_small(out, key="spent")
    t = Totals.of(lines)
    monthly = expense_budget(conn, months[-1])
    total_budget = monthly * n if monthly is not None else None
    return {
        "month": month,
        "period": period,
        "months": months,
        "currency": base_currency(),
        "lines": out,
        "income": in_base(t.income),
        "expenses": in_base(t.expenses),
        "budget": in_base(total_budget) if total_budget is not None else None,
        "rest_to_live": (in_base(total_budget - t.expenses) if total_budget is not None else None),
        "days_left": days_left(month, today) if period == "m" else 0,
        "over_count": sum(1 for i in out if i.get("over")),
    }


def budget_totals(conn: Connection, month: str, period: str) -> dict[str, Any]:
    months = period_months(month, period)
    t = Totals.of(lines_for(conn, months))
    monthly = expense_budget(conn, months[-1])
    total_budget = monthly * len(months) if monthly is not None else None
    return {
        "month": month,
        "period": period,
        "months": months,
        "currency": base_currency(),
        **totals_json(t),
        "budget": in_base(total_budget) if total_budget is not None else None,
        "budget_used": ratio(t.expenses, total_budget) if total_budget else None,
    }


def budget_months(conn: Connection, month: str, count: int) -> dict[str, Any]:
    months = [*previous_months(month, count - 1), month]
    series = []
    for m in months:
        series.append({"month": m, **totals_json(Totals.of(lines_for(conn, [m])))})
    return {"currency": base_currency(), "series": series}


# --- export -----------------------------------------------------------------------------------

EXPORT_COLUMNS = (
    "id",
    "booking_date",
    "value_date",
    "account",
    "account_iban",
    "kind",
    "amount",
    "currency",
    "counterparty",
    "counterparty_iban",
    "label",
    "remittance",
    "bank_ref",
    "bank_tx_code",
    "category",
    "category_source",
    "import_id",
)
_FORMULA = ("=", "+", "-", "@", "\t", "\r")


def _cell(value: object) -> str:
    """Texte libre : neutralise ce qu'un tableur prendrait pour une formule."""
    s = "" if value is None else str(value)
    return "'" + s if s.startswith(_FORMULA) else s


def export_csv(conn: Connection, date_from: str | None, date_to: str | None) -> Iterator[str]:
    """Journal complet, une ligne par écriture, par paquets de 500 lignes."""
    rows = conn.execute(
        text(
            "SELECT e.id, e.booking_date, e.value_date, a.name, a.iban, e.kind, e.amount_minor, "
            "e.currency, e.counterparty, e.counterparty_iban, e.label, e.remittance, e.bank_ref, "
            "e.bank_tx_code, vc.category_id, vc.source, e.import_id FROM entries e "
            "JOIN accounts a ON a.id = e.account_id "
            "LEFT JOIN v_entry_category vc ON vc.entry_seq = e.seq "
            "WHERE (:f IS NULL OR e.booking_date >= :f) AND (:t IS NULL OR e.booking_date <= :t) "
            "ORDER BY e.booking_date, e.seq"
        ),
        {"f": date_from, "t": date_to},
    )
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\r\n")
    writer.writerow(EXPORT_COLUMNS)
    for i, r in enumerate(rows, 1):
        writer.writerow(
            [
                r[0],
                r[1],
                r[2] or "",
                _cell(r[3]),
                r[4] or "",
                r[5],
                Money(int(r[6]), r[7]).display(),
                r[7],
                _cell(r[8]),
                r[9] or "",
                _cell(r[10]),
                _cell(r[11]),
                r[12] or "",
                r[13] or "",
                r[14] or "",
                r[15] or "",
                r[16] or "",
            ]
        )
        if i % 500 == 0:
            yield buf.getvalue()
            buf.seek(0)
            buf.truncate()
    yield buf.getvalue()
