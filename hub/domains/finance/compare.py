"""Comparaison de deux bases de la finance (ticket L4-08), `hub finance compare` : soldes par
compte, écritures, catégorie courante, totaux mensuels, notes, étiquettes, budgets, points de
contrôle, imports, opérations, positions, cours, change, compositions, virements appariés et
abonnements. Seuls des compteurs et des clés opaques (identifiants d'écriture, mois,
catégories) sortent, jamais un montant ni un libellé."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from sqlalchemy import Connection, Engine, text

if TYPE_CHECKING:
    pass


EXAMPLES = 5
Query = Callable[[Connection], dict[Any, Any]]


def _q(sql: str) -> Query:
    def run(conn: Connection) -> dict[Any, Any]:
        out: dict[Any, Any] = {}
        for r in conn.execute(text(sql)):
            key = r[0] if len(r) == 2 else tuple(r[:-1])
            out[key] = r[-1]
        return out

    return run


def _lines(conn: Connection) -> dict[Any, Any]:
    out: dict[str, list[tuple[str, int]]] = {}
    for entry_id, category, amount in conn.execute(
        text(
            "SELECT e.id, a.category_id, a.amount_minor FROM v_entry_allocation a "
            "JOIN entries e ON e.seq = a.entry_seq WHERE a.category_id IS NOT NULL"
        )
    ):
        out.setdefault(entry_id, []).append((category, int(amount)))
    return {k: sorted(v) for k, v in out.items()}


CHECKS: dict[str, Query] = {
    "balances": _q("SELECT account_id, sum(amount_minor) FROM entries GROUP BY account_id"),
    "entries": _q(
        "SELECT id, account_id || '|' || kind || '|' || booking_date || '|' || amount_minor "
        "FROM entries"
    ),
    "categories": _lines,
    "monthly_categories": _q(
        "SELECT substr(booking_date, 1, 7), coalesce(category_id, ''), sum(amount_minor) "
        "FROM v_entry_allocation GROUP BY 1, 2"
    ),
    "notes": _q(
        "SELECT e.id, count(*) FROM notes n JOIN entries e ON e.seq = n.entry_seq GROUP BY e.id"
    ),
    "taggings": _q(
        "SELECT e.id, t.tag_id, 1 FROM v_taggings t JOIN entries e ON e.seq = t.entry_seq"
    ),
    "budgets": _q("SELECT category_id, valid_from, monthly_minor || ' ' || currency FROM budgets"),
    "checkpoints": _q("SELECT account_id, on_date, kind, amount_minor FROM checkpoints"),
    "imports": _q("SELECT id, status FROM imports"),
    "trades": _q(
        "SELECT dedup_key, account_id || '|' || quantity || '|' || amount_minor FROM trades"
    ),
    "holdings": _q(
        "SELECT account_id, on_date, isin, quantity || '|' || value_minor FROM holdings "
        "ORDER BY seq"
    ),
    "prices": _q("SELECT isin, on_date, source, price FROM prices"),
    "fx": _q("SELECT on_date, base, quote, source, rate FROM fx_rates"),
    "compositions": _q(
        "SELECT isin, dimension, bucket, weight || '|' || on_date FROM compositions"
    ),
    # tables dérivées, recalculées après le rejeu
    "transfers": _q(
        "SELECT d.id, c.id, l.method FROM transfer_links l "
        "JOIN entries d ON d.seq = l.debit_seq JOIN entries c ON c.seq = l.credit_seq"
    ),
    "recurring": _q(
        "SELECT key, cadence || '|' || amount_minor || '|' || next_date FROM recurring"
    ),
}


@dataclass
class CompareReport:
    checks: dict[str, dict[str, Any]] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return all(c["differences"] == 0 for c in self.checks.values())

    def public(self) -> dict[str, Any]:
        return {"ok": self.ok, "checks": self.checks}


def _key(k: Any) -> str:
    return "/".join(map(str, k)) if isinstance(k, tuple) else str(k)


def compare(a: Engine, b: Engine) -> CompareReport:
    report = CompareReport()
    with a.connect() as ca, b.connect() as cb:
        for name, query in CHECKS.items():
            left, right = query(ca), query(cb)
            differing = sorted(
                (_key(k) for k in left.keys() | right.keys() if left.get(k) != right.get(k)),
            )
            report.checks[name] = {
                "source": len(left),
                "rebuilt": len(right),
                "differences": len(differing),
                # clés seules : identifiants d'écriture, comptes, mois, catégories
                "examples": differing[:EXAMPLES] if name not in ("balances",) else [],
            }
    return report
