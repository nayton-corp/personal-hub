"""Moteur de règles de catégorisation (ticket L3-01).

Une règle porte sur un champ, un sens et un motif ; la plus petite priorité gagne, puis
l'identifiant à priorité égale. Les règles ne remplacent jamais une catégorisation faite à la
main : elles ne touchent que les écritures sans catégorie ou déjà catégorisées par une règle.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import Connection, text

from hub.core.clock import now_iso
from hub.core.text import compact_iban, normalize
from hub.domains.finance import ledger

Field = Literal["search_text", "counterparty_iban", "bank_tx_code", "own_account"]
Direction = Literal["any", "debit", "credit"]
FIELDS: tuple[Field, ...] = ("search_text", "counterparty_iban", "bank_tx_code", "own_account")
DIRECTIONS: tuple[Direction, ...] = ("any", "debit", "credit")
# sources qu'une règle peut remplacer ; une décision humaine ne l'est jamais
RULE_OWNED = frozenset({"rule"})
SYSTEM_PREFIX = "system-"


class RuleError(ValueError):
    pass


@dataclass(frozen=True)
class Rule:
    id: str
    field: str
    pattern: str
    direction: str
    category_id: str
    priority: int
    active: bool = True
    account_id: str | None = None  # règle d'un seul compte (« tout débit de la poche Vacances »)

    def key(self) -> tuple[int, str]:
        return (self.priority, self.id)


@dataclass(frozen=True)
class Target:
    """Ce qu'une règle regarde d'une écriture : jamais plus."""

    amount_minor: int
    search_text: str
    counterparty_iban: str | None
    bank_tx_code: str | None
    account_iban: str | None = None
    account_id: str | None = None


def normalize_pattern(field: str, pattern: str) -> str:
    """Motif comparable au champ. Pour le texte, une espace en tête ou en fin est gardée : elle
    sert de limite de mot (« bar », « eni »). Un motif vide prend toute écriture du sens donné."""
    if field == "search_text":
        core = normalize(pattern)
        if not core:
            return ""
        lead = " " if pattern[:1].isspace() else ""
        trail = " " if pattern[-1:].isspace() else ""
        return f"{lead}{core}{trail}"
    if field == "counterparty_iban":
        value = compact_iban(pattern)
        if not value:
            raise RuleError("IBAN de contrepartie vide")
        return value
    if field == "bank_tx_code":
        value = pattern.strip().upper()
        if not value:
            raise RuleError("code de transaction vide")
        return value
    if field == "own_account":
        return "*"
    raise RuleError(f"champ inconnu : {field}")


def _direction_ok(direction: str, amount: int) -> bool:
    if direction == "debit":
        return amount < 0
    if direction == "credit":
        return amount > 0
    return True


class RuleSet:
    def __init__(self, rules: Iterable[Rule], own_ibans: Iterable[str] = ()) -> None:
        self.rules = sorted((r for r in rules if r.active), key=Rule.key)
        self.own = frozenset(own_ibans)

    def matches(self, rule: Rule, t: Target) -> bool:
        if not _direction_ok(rule.direction, t.amount_minor):
            return False
        if rule.account_id is not None and rule.account_id != t.account_id:
            return False
        if rule.field == "search_text":
            return rule.pattern in f" {t.search_text} "
        if rule.field == "counterparty_iban":
            return t.counterparty_iban == rule.pattern
        if rule.field == "bank_tx_code":
            return (t.bank_tx_code or "").upper().startswith(rule.pattern)
        if rule.field == "own_account":
            return bool(t.counterparty_iban) and (
                t.counterparty_iban in self.own and t.counterparty_iban != t.account_iban
            )
        return False

    def winner(self, t: Target) -> Rule | None:
        for rule in self.rules:
            if self.matches(rule, t):
                return rule
        return None

    def with_rule(self, rule: Rule) -> RuleSet:
        return RuleSet([*self.rules, rule], self.own)


# --- base ----------------------------------------------------------------------------------

_RULE_COLS = "id, field, pattern, direction, category_id, priority, active, account_id"


def _rule(r: Sequence[object]) -> Rule:
    return Rule(
        id=str(r[0]),
        field=str(r[1]),
        pattern=str(r[2]),
        direction=str(r[3]),
        category_id=str(r[4]),
        priority=int(str(r[5])),
        active=bool(r[6]),
        account_id=str(r[7]) if r[7] is not None else None,
    )


def list_rules(conn: Connection, *, active_only: bool = False) -> list[Rule]:
    where = " WHERE active = 1" if active_only else ""
    rows = conn.execute(text(f"SELECT {_RULE_COLS} FROM rules{where}"))  # noqa: S608
    return sorted((_rule(tuple(r)) for r in rows), key=Rule.key)


def get_rule(conn: Connection, rule_id: str) -> Rule | None:
    row = conn.execute(
        text(f"SELECT {_RULE_COLS} FROM rules WHERE id = :i"),  # noqa: S608
        {"i": rule_id},
    ).first()
    return _rule(tuple(row)) if row else None


def own_ibans(conn: Connection) -> frozenset[str]:
    rows = conn.execute(text("SELECT iban FROM accounts WHERE iban IS NOT NULL"))
    return frozenset(str(r[0]) for r in rows)


def load(conn: Connection) -> RuleSet:
    return RuleSet(list_rules(conn, active_only=True), own_ibans(conn))


def version(conn: Connection) -> int:
    return int(conn.execute(text("SELECT version FROM rules_meta")).scalar_one())


def bump_version(conn: Connection) -> int:
    conn.execute(text("UPDATE rules_meta SET version = version + 1"))
    return version(conn)


def rule_id(
    prefix: str,
    field: str,
    pattern: str,
    direction: str,
    category_id: str,
    account_id: str | None = None,
) -> str:
    """Identifiant déterministe : une même règle reprise deux fois garde le même."""
    seed = f"{field}|{pattern}|{direction}|{category_id}" + (f"|{account_id}" if account_id else "")
    digest = hashlib.sha256(seed.encode()).hexdigest()
    return f"{prefix}-{digest[:16]}"


def insert_rule(
    conn: Connection,
    *,
    id: str,
    field: str,
    pattern: str,
    direction: str,
    category_id: str,
    priority: int,
    proposal_id: str | None = None,
    account_id: str | None = None,
) -> Rule:
    if field not in FIELDS or field == "own_account":
        raise RuleError(f"champ non autorisé : {field}")
    if direction not in DIRECTIONS:
        raise RuleError(f"sens inconnu : {direction}")
    category = conn.execute(
        text("SELECT active FROM categories WHERE id = :c"), {"c": category_id}
    ).first()
    if category is None or not category[0]:
        raise RuleError(f"catégorie inconnue ou inactive : {category_id}")
    conn.execute(
        text(
            "INSERT INTO rules (id, field, pattern, direction, category_id, priority, active, "
            "proposal_id, created_at, account_id) "
            "VALUES (:id, :f, :p, :d, :c, :prio, 1, :prop, :at, :acc)"
        ),
        {
            "id": id,
            "f": field,
            "p": pattern,
            "d": direction,
            "c": category_id,
            "prio": priority,
            "prop": proposal_id,
            "at": now_iso(),
            "acc": account_id,
        },
    )
    return Rule(id, field, pattern, direction, category_id, priority, account_id=account_id)


def set_active(conn: Connection, rule_id: str, active: bool) -> None:
    conn.execute(
        text("UPDATE rules SET active = :a WHERE id = :i"), {"a": int(active), "i": rule_id}
    )


# --- application aux écritures --------------------------------------------------------------


@dataclass(frozen=True)
class Current:
    """Une écriture et sa dernière catégorisation."""

    entry_seq: int
    entry_id: str
    amount_minor: int
    currency: str
    category_id: str | None
    source: str | None
    categorization_seq: int | None
    target: Target


def candidates(conn: Connection) -> list[Current]:
    """Écritures que les règles ont le droit de toucher : sans catégorie, ou catégorisées par
    une règle. Les ouvertures et corrections n'en sont pas."""
    rows = conn.execute(
        text(
            "SELECT e.seq, e.id, e.amount_minor, e.currency, vc.category_id, vc.source, "
            "vc.categorization_seq, e.search_text, e.counterparty_iban, e.bank_tx_code, a.iban, "
            "e.account_id "
            "FROM entries e JOIN accounts a ON a.id = e.account_id "
            "LEFT JOIN v_entry_category vc ON vc.entry_seq = e.seq "
            "WHERE e.kind = 'movement' AND (vc.source IS NULL OR vc.source = 'rule') "
            "ORDER BY e.seq"
        )
    )
    return [
        Current(
            entry_seq=int(r[0]),
            entry_id=str(r[1]),
            amount_minor=int(r[2]),
            currency=str(r[3]),
            category_id=r[4],
            source=r[5],
            categorization_seq=r[6],
            target=Target(int(r[2]), str(r[7]), r[8], r[9], r[10], r[11]),
        )
        for r in rows
    ]


@dataclass(frozen=True)
class Change:
    current: Current
    rule: Rule


def changes(rules: RuleSet, items: Iterable[Current], *, only: Rule | None = None) -> list[Change]:
    """Ce qu'appliquer `rules` changerait ; avec `only`, seulement là où cette règle gagne."""
    out = []
    for c in items:
        won = rules.winner(c.target)
        if won is None or won.category_id == c.category_id:
            continue
        if only is not None and won.id != only.id:
            continue
        out.append(Change(c, won))
    return out


def categorize(
    conn: Connection, entry_seq: int, rule: Rule, *, proposal_id: str | None, created_at: str
) -> int:
    return ledger.append(
        conn,
        "categorizations",
        {
            "entry_seq": entry_seq,
            "category_id": rule.category_id,
            "source": "rule",
            "rule_id": rule.id,
            "proposal_id": proposal_id,
            "created_at": created_at,
        },
    )


def apply_changes(conn: Connection, found: Sequence[Change], proposal_id: str | None = None) -> int:
    created = now_iso()
    for ch in found:
        categorize(conn, ch.current.entry_seq, ch.rule, proposal_id=proposal_id, created_at=created)
    return len(found)


def run(conn: Connection) -> int:
    """Catégorise selon les règles actives tout ce qu'elles ont le droit de toucher."""
    return apply_changes(conn, changes(load(conn), candidates(conn)))
