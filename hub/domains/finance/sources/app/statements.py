"""Application d'un relevé au registre (section 4) : plan (écritures nouvelles, doublons,
écarts de solde), insertion, rapprochement du solde de clôture, mise en revue."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import Connection, text

from hub.domains.finance.classement.app import rules
from hub.domains.finance.registre.app import catalog, ledger
from hub.domains.finance.registre.model import dedup
from hub.domains.finance.registre.model.statements import (
    ParsedEntry,
    ParsedStatement,
)
from hub.domains.finance.sources.app.outcomes import StatementOutcome
from hub.kernel import canonical
from hub.kernel.clock import now_iso
from hub.kernel.ids import urn

APPLY_IMPORT = "apply_import"
# anomalies qu'une validation `apply_import` peut accepter ; les autres demandent d'abord un
# compte, une ouverture ou un relevé conforme
FORCEABLE: frozenset[str] = frozenset(
    {
        "internal_check_failed",
        "ledger_check_failed",
        "checkpoint_conflict",
        "near_duplicate",
        "grouped_not_split",
        "missing_balance",
    }
)


def source_of(conn: Connection, import_id: str) -> str | None:
    row = conn.execute(text("SELECT source FROM imports WHERE id = :i"), {"i": import_id}).first()
    return str(row[0]) if row else None


def _set_statement(
    conn: Connection, import_id: str, index: int, account_id: str | None, o: StatementOutcome
) -> None:
    conn.execute(
        text(
            "UPDATE import_statements SET account_id = :a, status = :s, reasons_json = :r, "
            "new_entries = :n, duplicates = :d, updated_at = :at "
            "WHERE import_id = :i AND stmt_index = :x"
        ),
        {
            "a": account_id,
            "s": o.status,
            "r": canonical.dumps(o.reasons),
            "n": o.new,
            "d": o.duplicates,
            "at": now_iso(),
            "i": import_id,
            "x": index,
        },
    )


@dataclass
class Plan:
    """Ce que le rapprochement d'un relevé a trouvé, avant toute écriture."""

    account: catalog.Account | None
    reasons: list[str]
    fresh: list[tuple[ParsedEntry, str]]
    checkpoints: list[tuple[str, str, int]]
    duplicates: int

    @property
    def blocking(self) -> list[str]:
        return sorted(set(self.reasons) - FORCEABLE)


def plan_statement(conn: Connection, st: ParsedStatement) -> Plan:
    """Contrôles du point 5 de la section 4, en lecture seule."""
    reasons: list[str] = list(st.anomalies)
    if st.account_ref is not None:
        account = catalog.account_by_ref(conn, st.account_ref)
    else:
        account = catalog.account_by_iban(conn, st.iban) if st.iban else None
    if account is None:
        reasons.append("unknown_account")
        return Plan(None, sorted(set(reasons)), [], [], 0)
    if st.currency is not None and st.currency != account.currency:
        reasons.append("currency_mismatch")
    opening = conn.execute(
        text("SELECT booking_date FROM entries WHERE account_id = :a AND kind = 'opening'"),
        {"a": account.id},
    ).first()
    if opening is None:
        reasons.append("no_opening")
    elif any(e.booking_date <= opening[0] for e in st.entries) or (
        st.closing is not None and st.closing.on_date < opening[0]
    ):
        reasons.append("before_opening")

    iban = account.iban or account.external_ref or ""
    keys = dedup.keys(iban, st.entries)
    existing = _existing_keys(conn, keys)
    fresh = [(e, k) for e, k in zip(st.entries, keys, strict=True) if k not in existing]
    statement_keys = set(keys)
    for e, _k in fresh:
        others = conn.execute(
            text(
                "SELECT dedup_key FROM entries WHERE account_id = :a AND booking_date = :d "
                "AND amount_minor = :m AND kind = 'movement'"
            ),
            {"a": account.id, "d": e.booking_date, "m": e.amount_minor},
        ).scalars()
        if any(k not in statement_keys for k in others):
            reasons.append("near_duplicate")
            break

    checkpoints: list[tuple[str, str, int]] = []
    # un relevé Revolut n'annonce qu'un solde final : contrôlé seul, sans ouverture annoncée
    if st.closing is not None and (st.opening is not None or st.account_ref is not None):
        announced = [("CLBD", st.closing)]
        if st.opening is not None:
            total = st.opening.amount_minor + sum(e.amount_minor for e in st.entries)
            if total != st.closing.amount_minor:
                reasons.append("internal_check_failed")
            announced.insert(0, ("OPBD", st.opening))
        for kind, bal in announced:
            known = conn.execute(
                text(
                    "SELECT amount_minor FROM checkpoints WHERE account_id = :a AND on_date = :d "
                    "AND kind = :k"
                ),
                {"a": account.id, "d": bal.on_date, "k": kind},
            ).scalar_one_or_none()
            if known is None:
                checkpoints.append((kind, bal.on_date, bal.amount_minor))
            elif known != bal.amount_minor:
                reasons.append("checkpoint_conflict")
        ledger_balance = conn.execute(
            text(
                "SELECT coalesce(sum(amount_minor), 0) FROM entries WHERE account_id = :a "
                "AND booking_date <= :d AND kind != 'correction'"
            ),
            {"a": account.id, "d": st.closing.on_date},
        ).scalar_one()
        ledger_balance += sum(
            e.amount_minor for e, _ in fresh if e.booking_date <= st.closing.on_date
        )
        if opening is not None and ledger_balance != st.closing.amount_minor:
            reasons.append("ledger_check_failed")
    return Plan(account, sorted(set(reasons)), fresh, checkpoints, len(st.entries) - len(fresh))


def _insert(conn: Connection, import_id: str, plan: Plan, proposal_id: str | None) -> None:
    """Point 6 : écritures, catégorisation par les règles, checkpoints, événement."""
    assert plan.account is not None  # noqa: S101 - garanti par l'appelant
    account = plan.account
    ruleset = rules.load(conn)
    created = now_iso()
    for e, key in plan.fresh:
        seq, _id = ledger.append_entry(
            conn,
            ledger.NewEntry(
                account_id=account.id,
                booking_date=e.booking_date,
                value_date=e.value_date,
                amount_minor=e.amount_minor,
                currency=e.currency,
                counterparty=e.counterparty,
                counterparty_iban=e.counterparty_iban,
                label=e.label,
                remittance=e.remittance,
                bank_ref=e.bank_ref,
                bank_tx_code=e.bank_tx_code,
                fx_json=e.fx_json,
                dedup_key=key,
                import_id=import_id,
            ),
            created,
        )
        target = rules.Target(
            e.amount_minor,
            ledger.search_text(e.counterparty, e.label, e.remittance),
            e.counterparty_iban,
            e.bank_tx_code,
            account.iban,
            account.id,
        )
        won = ruleset.winner(target)
        if won is not None:
            rules.categorize(conn, seq, won, proposal_id=proposal_id, created_at=created)
    for kind, on_date, amount in plan.checkpoints:
        ledger.append(
            conn,
            "checkpoints",
            {
                "account_id": account.id,
                "on_date": on_date,
                "kind": kind,
                "amount_minor": amount,
                "import_id": import_id,
            },
        )
    if plan.fresh:
        ledger.append_event(
            conn,
            "entries.appended",
            urn("finance", "account", account.id),
            {"import_id": import_id, "count": len(plan.fresh)},
        )


def _reconcile_and_apply(
    conn: Connection,
    import_id: str,
    st: ParsedStatement,
    *,
    force: bool = False,
    proposal_id: str | None = None,
) -> tuple[StatementOutcome, str | None]:
    plan = plan_statement(conn, st)
    account_id = plan.account.id if plan.account else None
    stopping = plan.blocking if force else plan.reasons
    if plan.account is None or stopping:
        return (
            StatementOutcome(import_id, st.index, "needs_review", plan.reasons, 0, plan.duplicates),
            account_id,
        )
    _insert(conn, import_id, plan, proposal_id)
    # validé malgré des anomalies : elles restent inscrites sur le relevé
    return (
        StatementOutcome(
            import_id, st.index, "applied", plan.reasons, len(plan.fresh), plan.duplicates
        ),
        account_id,
    )


def apply_statement(
    conn: Connection,
    import_id: str,
    st: ParsedStatement,
    *,
    force: bool = False,
    proposal_id: str | None = None,
) -> StatementOutcome:
    outcome, account_id = _reconcile_and_apply(
        conn, import_id, st, force=force, proposal_id=proposal_id
    )
    conn.execute(
        text(
            "UPDATE import_statements SET account_id = :a, status = :s, reasons_json = :r, "
            "new_entries = :n, duplicates = :d, updated_at = :at "
            "WHERE import_id = :i AND stmt_index = :x"
        ),
        {
            "a": account_id,
            "s": outcome.status,
            "r": canonical.dumps(outcome.reasons),
            "n": outcome.new,
            "d": outcome.duplicates,
            "at": now_iso(),
            "i": import_id,
            "x": st.index,
        },
    )
    return outcome


def finish(conn: Connection, import_id: str) -> str:
    """Statut et statistiques de l'import d'après ses relevés ; renvoie le statut."""
    rows = conn.execute(
        text(
            "SELECT status, reasons_json, new_entries, duplicates FROM import_statements "
            "WHERE import_id = :i ORDER BY stmt_index"
        ),
        {"i": import_id},
    ).fetchall()
    old = conn.execute(
        text("SELECT status, stats_json FROM imports WHERE id = :i"), {"i": import_id}
    ).one()
    applied = all(r[0] == "applied" for r in rows)
    reasons = sorted({x for r in rows for x in json.loads(r[1])})
    stats = {
        **json.loads(old[1]),
        "statements": len(rows),
        "new": sum(r[2] for r in rows),
        "duplicates": sum(r[3] for r in rows),
        "reasons": reasons,
    }
    status = "applied" if applied else "needs_review"
    conn.execute(
        text("UPDATE imports SET status = :s, stats_json = :j, updated_at = :at WHERE id = :i"),
        {"s": status, "j": canonical.dumps(stats), "at": now_iso(), "i": import_id},
    )
    target = urn("finance", "import", import_id)
    params = {"import_id": import_id}
    if applied and old[0] != "applied":
        ledger.append_event(
            conn, "import.applied", target, {"new": stats["new"], "duplicates": stats["duplicates"]}
        )
        if old[0] == "needs_review":
            # appliqué tout seul : sa carte `apply_import` éventuelle devient sans objet
            ledger.append_event(
                conn, "proposal.obsolete", target, {"kind": APPLY_IMPORT, "params": params}
            )
    elif not applied:
        request_review(conn, import_id)
    return status


def pending_reasons(conn: Connection, import_id: str) -> list[str]:
    rows = conn.execute(
        text(
            "SELECT reasons_json FROM import_statements WHERE import_id = :i "
            "AND status = 'needs_review'"
        ),
        {"i": import_id},
    ).fetchall()
    return sorted({x for r in rows for x in json.loads(r[0])})


def request_review(conn: Connection, import_id: str) -> bool:
    """Demande au cœur une carte `apply_import` si la validation peut lever toutes les
    anomalies ; sinon le relevé attend un compte, une ouverture ou un relevé conforme."""
    reasons = pending_reasons(conn, import_id)
    if not reasons or set(reasons) - FORCEABLE:
        return False
    ledger.append_event(
        conn,
        "proposal.request",
        urn("finance", "import", import_id),
        {
            "kind": APPLY_IMPORT,
            "params": {"import_id": import_id},
            "reason": "relevé en attente de validation",
        },
    )
    return True


def _existing_keys(conn: Connection, keys: Sequence[str]) -> set[str]:
    found: set[str] = set()
    for i in range(0, len(keys), 500):
        chunk = keys[i : i + 500]
        marks = ",".join(f":k{j}" for j in range(len(chunk)))
        found.update(
            conn.execute(
                text(f"SELECT dedup_key FROM entries WHERE dedup_key IN ({marks})"),
                {f"k{j}": k for j, k in enumerate(chunk)},
            ).scalars()
        )
    return found
