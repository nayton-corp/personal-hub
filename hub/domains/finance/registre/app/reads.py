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

from hub.domains.finance.packs import CountryPack
from hub.domains.finance.packs import instance as packs
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


# le dernier solde de clôture annoncé de chaque compte, et la somme des écritures jusqu'à lui :
# une requête pour tous les comptes (audit m17)
_LAST_CLBDS = (
    "SELECT c.account_id, c.on_date, c.amount_minor, a.currency, "
    "(SELECT coalesce(sum(e.amount_minor), 0) FROM entries e "
    "WHERE e.account_id = c.account_id AND e.booking_date <= c.on_date) "
    "FROM checkpoints c JOIN accounts a ON a.id = c.account_id "
    "WHERE c.kind = 'CLBD' AND (:a IS NULL OR c.account_id = :a) "
    "AND c.on_date = (SELECT max(x.on_date) FROM checkpoints x "
    "WHERE x.account_id = c.account_id AND x.kind = 'CLBD')"
)


def closing_balances(conn: Connection, account_id: str | None = None) -> dict[str, dict[str, Any]]:
    """{compte: dernier solde de clôture (date, montant, écart avec les écritures)}."""
    out: dict[str, dict[str, Any]] = {}
    for account, on, amount, ccy, computed in conn.execute(text(_LAST_CLBDS), {"a": account_id}):
        out[str(account)] = {
            "on_date": on,
            "amount": money(amount, ccy),
            "gap": money(int(computed) - int(amount), ccy),
        }
    return out


def last_clbd(conn: Connection, account_id: str) -> dict[str, Any] | None:
    return closing_balances(conn, account_id).get(account_id)


# Une donnée d'un compte : écriture, position relevée, ordre ou solde de clôture. Seuls les
# relevés bancaires ont un solde de clôture ; Revolut, les cryptos ou les titres n'en ont pas.
# Une requête pour tous les comptes (audit m17), ou pour un seul (:a)
_LAST_DATA = (
    "SELECT account_id, max(d) FROM ("
    "SELECT account_id, max(booking_date) AS d FROM entries WHERE kind != 'correction' "
    "GROUP BY account_id "
    "UNION ALL SELECT account_id, max(on_date) FROM holdings GROUP BY account_id "
    "UNION ALL SELECT account_id, max(trade_date) FROM trades GROUP BY account_id "
    "UNION ALL SELECT account_id, max(on_date) FROM checkpoints WHERE kind = 'CLBD' "
    "GROUP BY account_id) WHERE d IS NOT NULL AND (:a IS NULL OR account_id = :a) "
    "GROUP BY account_id"
)
# un import compte pour chaque compte qu'il a alimenté, y compris les comptes créés à sa lecture
# (sous-comptes IBKR par devise), pas seulement pour le compte de son relevé
_LAST_IMPORTS = (
    "SELECT x.account_id, max(i.received_at) FROM imports i JOIN ("
    "SELECT account_id, import_id FROM import_statements WHERE status = 'applied' "
    "UNION SELECT account_id, import_id FROM entries "
    "UNION SELECT account_id, import_id FROM holdings "
    "UNION SELECT account_id, import_id FROM trades) x ON x.import_id = i.id "
    "GROUP BY x.account_id"
)


def last_dates(conn: Connection, account_id: str | None = None) -> dict[str, str]:
    """{compte: date de sa dernière donnée (écriture, position, ordre, solde de clôture)}."""
    return {str(a): str(d) for a, d in conn.execute(text(_LAST_DATA), {"a": account_id})}


def last_data(conn: Connection, account_id: str) -> str | None:
    return last_dates(conn, account_id).get(account_id)


def freshness(conn: Connection) -> list[dict[str, Any]]:
    rows = conn.execute(text("SELECT id, name, institution, hidden FROM accounts ORDER BY name"))
    imports = {str(a): str(at) for a, at in conn.execute(text(_LAST_IMPORTS))}
    dates, clbds = last_dates(conn), closing_balances(conn)
    return [
        {
            "account_id": a[0],
            "name": a[1],
            "institution": a[2],
            "hidden": bool(a[3]),
            "last_import": imports.get(a[0]),
            "last_data": dates.get(a[0]),
            "last_clbd": clbds.get(a[0]),
            "collector": None,  # collecteurs : lot 5
        }
        for a in rows.fetchall()
    ]


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


def _entry(r: Any, pack: CountryPack) -> dict[str, Any]:
    return {
        "id": r[1],
        "account_id": r[2],
        "kind": r[3],
        "booking_date": r[4],
        "value_date": r[5],
        "amount": money(r[6], r[7]),
        "counterparty": ledger.party(r[8]),
        # commerçant lu dans le libellé (carte, TWINT) : motif de « Toujours », titre dans l'app
        "merchant": merchant.key(r[10], pack),
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
    pack = packs.current()
    return [_entry(r, pack) for r in page], next_cursor


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
    out = _entry(row, packs.current())
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
    pack = packs.current()
    return [_entry(r, pack) for r in rows]


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
