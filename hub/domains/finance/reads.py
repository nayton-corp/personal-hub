"""Lectures du registre (ticket L1-10) : écritures, soldes, résumés, recherche.

Les montants sortent toujours en `{"minor", "currency", "display"}`. Pour la portée
`aggregates`, une catégorie qui compte moins de 3 écritures sur la période est regroupée dans
« Autres » : un total ne doit pas révéler une transaction.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import Connection, text

from hub.core.money import Money
from hub.core.text import mask_iban, normalize

OTHERS = "autres"
MIN_COUNT_FOR_AGGREGATES = 3
UNCATEGORIZED = "a-categoriser"
SEARCH_LIMIT = 50


def money(minor: int, currency: str) -> dict[str, int | str]:
    return Money(int(minor), currency).to_api()


def month_bounds(month: str) -> tuple[str, str]:
    y, m = (int(x) for x in month.split("-"))
    start = date(y, m, 1)
    end = date(y + (m == 12), m % 12 + 1, 1)
    return start.isoformat(), end.isoformat()


def shift_month(month: str, delta: int) -> str:
    y, m = (int(x) for x in month.split("-"))
    index = y * 12 + (m - 1) + delta
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def _budget_accounts(conn: Connection) -> list[str]:
    flagged = conn.execute(text("SELECT id FROM accounts WHERE budget_account = 1")).scalars()
    ids = list(flagged)
    if ids:
        return ids
    return list(conn.execute(text("SELECT id FROM accounts WHERE kind = 'cash'")).scalars())


def _in(name: str, values: list[str]) -> tuple[str, dict[str, str]]:
    if not values:
        return "(NULL)", {}
    marks = ",".join(f":{name}{i}" for i in range(len(values)))
    return f"({marks})", {f"{name}{i}": v for i, v in enumerate(values)}


# --- comptes et fraîcheur -------------------------------------------------------------------


def accounts(conn: Connection) -> list[dict[str, Any]]:
    out = []
    rows = conn.execute(
        text(
            "SELECT a.id, a.institution, a.name, a.kind, a.currency, a.iban, a.liquid, "
            "a.budget_account, coalesce(b.balance_minor, 0), b.last_booking "
            "FROM accounts a LEFT JOIN v_balances b ON b.account_id = a.id "
            "ORDER BY a.institution, a.name"
        )
    ).fetchall()
    for r in rows:
        clbd = last_clbd(conn, r[0])
        out.append(
            {
                "id": r[0],
                "institution": r[1],
                "name": r[2],
                "kind": r[3],
                "iban": mask_iban(r[5]),
                "liquid": bool(r[6]),
                "budget_account": bool(r[7]),
                "balance": money(r[8], r[4]),
                "last_booking": r[9],
                "last_clbd": clbd,
            }
        )
    return out


def last_clbd(conn: Connection, account_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        text(
            "SELECT c.on_date, c.amount_minor, a.currency FROM checkpoints c "
            "JOIN accounts a ON a.id = c.account_id WHERE c.account_id = :a AND c.kind = 'CLBD' "
            "ORDER BY c.on_date DESC LIMIT 1"
        ),
        {"a": account_id},
    ).first()
    if row is None:
        return None
    computed = conn.execute(
        text(
            "SELECT coalesce(sum(amount_minor), 0) FROM entries WHERE account_id = :a "
            "AND booking_date <= :d AND kind != 'correction'"
        ),
        {"a": account_id, "d": row[0]},
    ).scalar_one()
    return {
        "on_date": row[0],
        "amount": money(row[1], row[2]),
        "gap": money(computed - row[1], row[2]),
    }


def freshness(conn: Connection) -> list[dict[str, Any]]:
    out = []
    for a in conn.execute(text("SELECT id, name FROM accounts ORDER BY name")).fetchall():
        last_import = conn.execute(
            text(
                "SELECT max(i.received_at) FROM imports i JOIN import_statements s "
                "ON s.import_id = i.id WHERE s.account_id = :a AND s.status = 'applied'"
            ),
            {"a": a[0]},
        ).scalar_one()
        clbd = last_clbd(conn, a[0])
        out.append(
            {
                "account_id": a[0],
                "name": a[1],
                "last_import": last_import,
                "last_clbd": clbd,
                "collector": None,  # collecteurs : lot 5
            }
        )
    return out


def categories(conn: Connection) -> list[dict[str, Any]]:
    rows = conn.execute(text("SELECT id, name, grp, active FROM categories ORDER BY grp, name"))
    return [{"id": r[0], "name": r[1], "group": r[2], "active": bool(r[3])} for r in rows]


# --- écritures --------------------------------------------------------------------------------

_ENTRY_COLS = (
    "e.seq, e.id, e.account_id, e.kind, e.booking_date, e.value_date, e.amount_minor, "
    "e.currency, e.counterparty, e.counterparty_iban, e.label, e.remittance, e.bank_tx_code, "
    "vc.category_id, vc.source"
)


def _entry(r: Any) -> dict[str, Any]:
    return {
        "id": r[1],
        "account_id": r[2],
        "kind": r[3],
        "booking_date": r[4],
        "value_date": r[5],
        "amount": money(r[6], r[7]),
        "counterparty": r[8],
        "counterparty_iban": mask_iban(r[9]),
        "label": r[10],
        "remittance": r[11],
        "bank_tx_code": r[12],
        "category": {"id": r[13], "source": r[14]} if r[13] else None,
    }


@dataclass(frozen=True)
class EntryFilter:
    account: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    category: str | None = None
    uncategorized: bool = False


def encode_cursor(booking_date: str, seq: int) -> str:
    return f"{booking_date}~{seq}"


def decode_cursor(cursor: str) -> tuple[str, int]:
    d, _, s = cursor.partition("~")
    date.fromisoformat(d)
    return d, int(s)


def entries(
    conn: Connection, f: EntryFilter, cursor: str | None, limit: int
) -> tuple[list[dict[str, Any]], str | None]:
    where = ["1 = 1"]
    params: dict[str, Any] = {"lim": limit + 1}
    if f.account:
        where.append("e.account_id = :acc")
        params["acc"] = f.account
    if f.date_from:
        where.append("e.booking_date >= :df")
        params["df"] = f.date_from
    if f.date_to:
        where.append("e.booking_date <= :dt")
        params["dt"] = f.date_to
    if f.category:
        where.append("vc.category_id = :cat")
        params["cat"] = f.category
    if f.uncategorized:
        where.append("vc.category_id IS NULL AND e.kind = 'movement'")
    if cursor:
        d, s = decode_cursor(cursor)
        where.append("(e.booking_date < :cd OR (e.booking_date = :cd AND e.seq < :cs))")
        params.update(cd=d, cs=s)
    rows = conn.execute(
        text(
            f"SELECT {_ENTRY_COLS} FROM entries e "
            "LEFT JOIN v_entry_category vc ON vc.entry_seq = e.seq "
            f"WHERE {' AND '.join(where)} ORDER BY e.booking_date DESC, e.seq DESC LIMIT :lim"
        ),
        params,
    ).fetchall()
    page = rows[:limit]
    next_cursor = encode_cursor(page[-1][4], page[-1][0]) if len(rows) > limit else None
    return [_entry(r) for r in page], next_cursor


def entry_detail(conn: Connection, entry_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        text(
            f"SELECT {_ENTRY_COLS} FROM entries e "
            "LEFT JOIN v_entry_category vc ON vc.entry_seq = e.seq WHERE e.id = :id"
        ),
        {"id": entry_id},
    ).first()
    if row is None:
        return None
    seq = row[0]
    out = _entry(row)
    out["categorizations"] = [
        {"category_id": c[0], "source": c[1], "rule_id": c[2], "at": c[3]}
        for c in conn.execute(
            text(
                "SELECT category_id, source, rule_id, created_at FROM categorizations "
                "WHERE entry_seq = :s ORDER BY seq"
            ),
            {"s": seq},
        )
    ]
    out["notes"] = [
        {"text": n[0], "at": n[1]}
        for n in conn.execute(
            text("SELECT text, created_at FROM notes WHERE entry_seq = :s ORDER BY seq"), {"s": seq}
        )
    ]
    out["corrections"] = [
        {"id": c[0], "amount": money(c[1], c[2]), "booking_date": c[3]}
        for c in conn.execute(
            text(
                "SELECT id, amount_minor, currency, booking_date FROM entries "
                "WHERE corrects_seq = :s ORDER BY seq"
            ),
            {"s": seq},
        )
    ]
    return out


# --- agrégats ---------------------------------------------------------------------------------


def _merge_small(rows: list[dict[str, Any]], currency: str) -> list[dict[str, Any]]:
    kept = [r for r in rows if r["count"] >= MIN_COUNT_FOR_AGGREGATES]
    small = [r for r in rows if r["count"] < MIN_COUNT_FOR_AGGREGATES]
    if small:
        kept.append(
            {
                "category": OTHERS,
                "group": "mixed",
                "total": money(sum(r["total"]["minor"] for r in small), currency),
                "count": sum(r["count"] for r in small),
            }
        )
    return kept


def summary(
    conn: Connection, month: str, *, aggregates_only: bool, currency: str = "CHF"
) -> dict[str, Any]:
    start, end = month_bounds(month)
    ids, params = _in("a", _budget_accounts(conn))
    rows = conn.execute(
        text(
            "SELECT coalesce(v.category_id, :unc), coalesce(c.grp, 'uncategorized'), "
            "sum(v.amount_minor), count(DISTINCT v.entry_seq) "
            "FROM v_entry_allocation v JOIN entries e ON e.seq = v.entry_seq "
            "LEFT JOIN categories c ON c.id = v.category_id "
            f"WHERE v.account_id IN {ids} AND v.currency = :ccy AND e.kind != 'opening' "
            "AND v.booking_date >= :s AND v.booking_date < :e "
            "GROUP BY 1, 2 ORDER BY 3"
        ),
        {**params, "unc": UNCATEGORIZED, "ccy": currency, "s": start, "e": end},
    ).fetchall()
    by_category = [
        {"category": r[0], "group": r[1], "total": money(r[2], currency), "count": r[3]}
        for r in rows
    ]
    groups: dict[str, int] = {}
    for r in rows:
        groups[r[1]] = groups.get(r[1], 0) + int(r[2])
    expenses = -(groups.get("fixed", 0) + groups.get("variable", 0))
    if aggregates_only:
        by_category = _merge_small(by_category, currency)
    return {
        "month": month,
        "currency": currency,
        "income": money(groups.get("income", 0), currency),
        "expenses": money(expenses, currency),
        "savings": money(-groups.get("savings", 0), currency),
        "transfers": money(groups.get("transfer", 0), currency),
        "uncategorized": money(groups.get("uncategorized", 0), currency),
        "by_group": {g: money(v, currency) for g, v in sorted(groups.items())},
        "by_category": by_category,
    }


def trend(
    conn: Connection, category: str | None, months: int, until: str, currency: str = "CHF"
) -> list[dict[str, Any]]:
    first = shift_month(until, -(months - 1))
    start, _ = month_bounds(first)
    _, end = month_bounds(until)
    ids, params = _in("a", _budget_accounts(conn))
    cat_clause = "AND v.category_id = :cat" if category else "AND c.grp IN ('fixed', 'variable')"
    rows = conn.execute(
        text(
            "SELECT substr(v.booking_date, 1, 7), sum(v.amount_minor), count(*) "
            "FROM v_entry_allocation v JOIN entries e ON e.seq = v.entry_seq "
            "LEFT JOIN categories c ON c.id = v.category_id "
            f"WHERE v.account_id IN {ids} AND v.currency = :ccy AND e.kind = 'movement' "
            f"AND v.booking_date >= :s AND v.booking_date < :e {cat_clause} GROUP BY 1"
        ),
        {**params, "ccy": currency, "s": start, "e": end, "cat": category},
    ).fetchall()
    found = {r[0]: (int(r[1]), int(r[2])) for r in rows}
    series = []
    for i in range(months):
        m = shift_month(first, i)
        total, count = found.get(m, (0, 0))
        series.append({"month": m, "total": money(total, currency), "count": count})
    return series


def budget(conn: Connection, month: str, *, aggregates_only: bool) -> dict[str, Any]:
    """Réel et cible par catégorie ; les cibles arrivent par proposition au lot 3."""
    s = summary(conn, month, aggregates_only=aggregates_only)
    targets = {
        r[0]: (int(r[1]), r[2])
        for r in conn.execute(
            text(
                "SELECT b.category_id, b.monthly_minor, b.currency FROM budgets b "
                "WHERE b.seq = (SELECT max(seq) FROM budgets WHERE category_id = b.category_id "
                "AND valid_from <= :m)"
            ),
            {"m": f"{month}-01"},
        )
    }
    lines = []
    for row in s["by_category"]:
        target = targets.get(row["category"])
        spent = -row["total"]["minor"]
        lines.append(
            {
                "category": row["category"],
                "spent": money(spent, s["currency"]),
                "target": money(target[0], target[1]) if target else None,
                "over": bool(target and spent > target[0]),
            }
        )
    return {"month": month, "lines": lines, "income": s["income"], "expenses": s["expenses"]}


def review(conn: Connection, limit: int = 100) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            "SELECT e.counterparty, e.currency, e.amount_minor FROM entries e "
            "LEFT JOIN v_entry_category vc ON vc.entry_seq = e.seq "
            "WHERE vc.category_id IS NULL AND e.kind = 'movement'"
        )
    ).fetchall()
    groups: dict[tuple[str, str], list[int]] = {}
    for cp, ccy, amount in rows:
        groups.setdefault((normalize(cp) or "(inconnu)", ccy), []).append(int(amount))
    out: list[dict[str, Any]] = [
        {"counterparty": k[0], "count": len(v), "total": money(sum(v), k[1])}
        for k, v in groups.items()
    ]
    out.sort(key=lambda g: (-g["count"], g["counterparty"]))
    return out[:limit]


def fts_query(q: str) -> str | None:
    """Requête normalisée entre guillemets ; trigram exige au moins 3 caractères."""
    value = normalize(q)
    if len(value) < 3:
        return None
    return '"' + value.replace('"', '""') + '"'


def search(conn: Connection, q: str, limit: int = SEARCH_LIMIT) -> list[dict[str, Any]]:
    query = fts_query(q)
    if query is None:
        return []
    rows = conn.execute(
        text(
            f"SELECT {_ENTRY_COLS}, bm25(entries_fts) AS score FROM entries_fts "
            "JOIN entries e ON e.seq = entries_fts.rowid "
            "LEFT JOIN v_entry_category vc ON vc.entry_seq = e.seq "
            "WHERE entries_fts MATCH :q ORDER BY score, e.booking_date DESC LIMIT :n"
        ),
        {"q": query, "n": limit},
    ).fetchall()
    return [_entry(r) for r in rows]


def import_detail(conn: Connection, import_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        text(
            "SELECT id, source, file_name, received_at, status, stats_json FROM imports "
            "WHERE id = :i"
        ),
        {"i": import_id},
    ).first()
    if row is None:
        return None
    statements = [
        {
            "index": s[0],
            "account_id": s[1],
            "opbd_date": s[2],
            "clbd_date": s[3],
            "status": s[4],
            "reasons": json.loads(s[5]),
            "new": s[6],
            "duplicates": s[7],
        }
        for s in conn.execute(
            text(
                "SELECT stmt_index, account_id, opbd_date, clbd_date, status, reasons_json, "
                "new_entries, duplicates FROM import_statements WHERE import_id = :i "
                "ORDER BY stmt_index"
            ),
            {"i": import_id},
        )
    ]
    return {
        "id": row[0],
        "source": row[1],
        "file_name": row[2],
        "received_at": row[3],
        "status": row[4],
        "stats": json.loads(row[5]),
        "statements": statements,
        "proposal_id": None,  # apply_import : lot 3
    }
