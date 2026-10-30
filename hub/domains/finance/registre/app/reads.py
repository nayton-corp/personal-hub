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

from hub.domains.finance.registre.app import ledger
from hub.domains.finance.registre.model import merchant
from hub.domains.finance.registre.model.amounts import (
    money,
)
from hub.kernel.text import mask_iban, normalize

SEARCH_LIMIT = 50


def budget_accounts(conn: Connection) -> list[str]:
    flagged = conn.execute(text("SELECT id FROM accounts WHERE budget_account = 1")).scalars()
    ids = list(flagged)
    if ids:
        return ids
    return list(conn.execute(text("SELECT id FROM accounts WHERE kind = 'cash'")).scalars())


def in_list(name: str, values: list[str]) -> tuple[str, dict[str, str]]:
    if not values:
        return "(NULL)", {}
    marks = ",".join(f":{name}{i}" for i in range(len(values)))
    return f"({marks})", {f"{name}{i}": v for i, v in enumerate(values)}


# --- comptes et fraîcheur -------------------------------------------------------------------


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


# Une donnée d'un compte : écriture, position relevée, ordre ou solde de clôture. Seuls les
# relevés bancaires ont un solde de clôture ; Revolut, les cryptos ou les titres n'en ont pas.
_LAST_DATA = (
    "SELECT max(d) FROM ("
    "SELECT max(booking_date) AS d FROM entries WHERE account_id = :a AND kind != 'correction' "
    "UNION ALL SELECT max(on_date) FROM holdings WHERE account_id = :a "
    "UNION ALL SELECT max(trade_date) FROM trades WHERE account_id = :a "
    "UNION ALL SELECT max(on_date) FROM checkpoints WHERE account_id = :a AND kind = 'CLBD')"
)
# un import compte pour chaque compte qu'il a alimenté, y compris les comptes créés à sa lecture
# (sous-comptes IBKR par devise), pas seulement pour le compte de son relevé
_LAST_IMPORT = (
    "SELECT max(i.received_at) FROM imports i WHERE i.id IN ("
    "SELECT import_id FROM import_statements WHERE account_id = :a AND status = 'applied' "
    "UNION SELECT import_id FROM entries WHERE account_id = :a "
    "UNION SELECT import_id FROM holdings WHERE account_id = :a "
    "UNION SELECT import_id FROM trades WHERE account_id = :a)"
)


def last_data(conn: Connection, account_id: str) -> str | None:
    d = conn.execute(text(_LAST_DATA), {"a": account_id}).scalar_one()
    return str(d) if d is not None else None


def freshness(conn: Connection) -> list[dict[str, Any]]:
    out = []
    rows = conn.execute(text("SELECT id, name, institution, hidden FROM accounts ORDER BY name"))
    for a in rows.fetchall():
        out.append(
            {
                "account_id": a[0],
                "name": a[1],
                "institution": a[2],
                "hidden": bool(a[3]),
                "last_import": conn.execute(text(_LAST_IMPORT), {"a": a[0]}).scalar_one(),
                "last_data": last_data(conn, a[0]),
                "last_clbd": last_clbd(conn, a[0]),
                "collector": None,  # collecteurs : lot 5
            }
        )
    return out


TRADES_LIMIT = 200  # ordres montrés pour un actif dans l'app


def trades(conn: Connection, isin: str, account: str | None = None) -> list[dict[str, Any]]:
    """Achats (+) et ventes (−) d'un actif, les plus récents d'abord."""
    rows = conn.execute(
        text(
            "SELECT t.seq, t.account_id, t.trade_date, t.isin, t.quantity, t.amount_minor, "
            "t.currency, i.name FROM trades t LEFT JOIN instruments i ON i.isin = t.isin "
            "WHERE t.isin = :i AND (:a IS NULL OR t.account_id = :a) "
            "ORDER BY t.trade_date DESC, t.seq DESC LIMIT :n"
        ),
        {"i": isin, "a": account, "n": TRADES_LIMIT},
    ).fetchall()
    return [
        {
            "id": r[0],
            "account_id": r[1],
            "trade_date": r[2],
            "isin": r[3],
            "name": r[7] or r[3],
            "quantity": r[4],
            "amount": money(int(r[5]), r[6]),
        }
        for r in rows
    ]


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
        "counterparty": ledger.party(r[8]),
        # commerçant lu dans le libellé (carte, TWINT) : motif de « Toujours », titre dans l'app
        "merchant": merchant.key(r[10]),
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
    direction: str | None = None  # "in" (crédits) ou "out" (débits)
    min_minor: int | None = None  # montant absolu, bornes comprises
    max_minor: int | None = None
    q: str | None = None  # recherche plein texte (contrepartie, libellé, communication)
    sort: str = "date"  # "date" (récentes d'abord) ou "amount" (plus gros montants d'abord)


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
    if f.direction:
        where.append("e.amount_minor > 0" if f.direction == "in" else "e.amount_minor < 0")
    if f.min_minor is not None:
        where.append("abs(e.amount_minor) >= :amin")
        params["amin"] = f.min_minor
    if f.max_minor is not None:
        where.append("abs(e.amount_minor) <= :amax")
        params["amax"] = f.max_minor
    if f.q:
        query = fts_query(f.q)
        if query is None:
            return [], None
        where.append("e.seq IN (SELECT rowid FROM entries_fts WHERE entries_fts MATCH :q)")
        params["q"] = query
    by_amount = f.sort == "amount"
    if cursor:
        if by_amount:
            a, _, sq = cursor.partition("~")
            where.append(
                "(abs(e.amount_minor) < :ca OR (abs(e.amount_minor) = :ca AND e.seq < :cs))"
            )
            params.update(ca=int(a), cs=int(sq))
        else:
            d, s = decode_cursor(cursor)
            where.append("(e.booking_date < :cd OR (e.booking_date = :cd AND e.seq < :cs))")
            params.update(cd=d, cs=s)
    order = (
        "abs(e.amount_minor) DESC, e.seq DESC" if by_amount else "e.booking_date DESC, e.seq DESC"
    )
    rows = conn.execute(
        text(
            f"SELECT {_ENTRY_COLS} FROM entries e "
            "LEFT JOIN v_entry_shown vc ON vc.entry_seq = e.seq "
            f"WHERE {' AND '.join(where)} ORDER BY {order} LIMIT :lim"
        ),
        params,
    ).fetchall()
    page = rows[:limit]
    next_cursor = None
    if len(rows) > limit:
        last = page[-1]
        next_cursor = (
            f"{abs(int(last[6]))}~{last[0]}" if by_amount else encode_cursor(last[4], last[0])
        )
    return [_entry(r) for r in page], next_cursor


def entry_detail(conn: Connection, entry_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        text(
            f"SELECT {_ENTRY_COLS} FROM entries e "
            "LEFT JOIN v_entry_shown vc ON vc.entry_seq = e.seq WHERE e.id = :id"
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
            "LEFT JOIN v_entry_shown vc ON vc.entry_seq = e.seq "
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
        "proposal_id": None,  # carte apply_import : ajoutée par la route (core.db)
    }
