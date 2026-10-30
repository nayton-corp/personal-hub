"""Reconstruction du registre par rejeu (ticket L4-08), `hub finance rebuild`.

`rebuild` part d'une base neuve à la dernière migration et rejoue ce qui a construit la base
d'origine : les données de référence (devises, catégories, comptes avec leurs identifiants,
règles dans leur état final, cours de change, étiquettes), les écritures d'ouverture, puis,
dans l'ordre chronologique, chaque import relu depuis son archive chiffrée (même identifiant)
et chaque proposition validée du domaine (même identifiant, paramètres lus dans `core.db`).
Les règles tournent une dernière fois à la fin. La base reconstruite ouvre une nouvelle époque
du journal (`rebuild_meta`).

La comparaison des deux bases est dans compare.py.

Écart attendu : une catégorie posée par une règle depuis désactivée ou modifiée, que la base
d'origine garde et que le rejeu (avec les règles finales) ne reproduit pas.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from sqlalchemy import Connection, Engine, text

from hub.core.errors import Problem
from hub.domains.finance.classement.app import rules
from hub.domains.finance.port import Finance
from hub.domains.finance.registre.app import ledger, opening
from hub.domains.finance.registre.model import errors, hashing
from hub.domains.finance.sources.infra.viac import ViacError
from hub.kernel.clock import now_iso
from hub.platform import secrets
from hub.platform.db import begin_immediate
from hub.platform.logging import get_logger

if TYPE_CHECKING:
    from hub.core.domain import LocalHandler

log = get_logger("hub.finance.rebuild")

# propositions dont l'effet est déjà dans les données de référence copiées
REFERENCE_KINDS = frozenset(
    {
        "create_account",
        "create_category",
        "create_rule",
        "disable_rule",
        "save_debt",
        "record_debt_balance",
    }
)


@dataclass(frozen=True)
class Applied:
    """Une proposition validée à rejouer."""

    proposal_id: str
    kind: str
    applied_at: str
    params: dict[str, Any] | None  # None : absente de core.db


@dataclass
class RebuildReport:
    ok: bool = True
    epoch: int = 0
    imports: int = 0
    proposals: int = 0
    skipped: dict[str, int] = field(default_factory=dict)  # motif -> nombre
    error: str | None = None

    def skip(self, reason: str) -> None:
        self.skipped[reason] = self.skipped.get(reason, 0) + 1

    def public(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "epoch": self.epoch,
            "imports": self.imports,
            "proposals": self.proposals,
            "skipped": self.skipped,
            "error": self.error,
        }


def applied_proposals(source: Engine, core: Engine) -> list[Applied]:
    """`applied_proposals` du domaine fait foi ; les paramètres viennent de `core.db`."""
    with source.connect() as conn:
        rows = conn.execute(
            text("SELECT proposal_id, kind, applied_at FROM applied_proposals ORDER BY rowid")
        ).fetchall()
    with core.connect() as conn:
        params = {
            r[0]: json.loads(r[1])
            for r in conn.execute(
                text("SELECT id, params_json FROM proposals WHERE domain = 'finance'")
            )
        }
    return [Applied(r[0], r[1], r[2], params.get(r[0])) for r in rows]


# --- copie des données de référence --------------------------------------------------------


def _columns(conn: Connection, table: str) -> list[str]:
    return [str(r[1]) for r in conn.execute(text(f"PRAGMA table_info({table})"))]


def _rows(conn: Connection, table: str, order: str) -> tuple[list[str], list[dict[str, Any]]]:
    cols = _columns(conn, table)
    rows = conn.execute(text(f"SELECT {', '.join(cols)} FROM {table} ORDER BY {order}"))  # noqa: S608
    return cols, [dict(zip(cols, r, strict=True)) for r in rows]


def _upsert(
    conn: Connection, table: str, key: str, cols: list[str], rows: list[dict[str, Any]]
) -> None:
    if not rows:
        return
    updates = ", ".join(f"{c} = excluded.{c}" for c in cols if c != key)
    conn.execute(
        text(
            f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(':' + c for c in cols)}) "  # noqa: S608
            f"ON CONFLICT ({key}) DO UPDATE SET {updates}"
        ),
        rows,
    )


def copy_reference(src: Connection, dst: Connection) -> None:
    for table, key in (("currencies", "code"), ("categories", "id"), ("accounts", "id")):
        cols, rows = _rows(src, table, key)
        _upsert(dst, table, key, cols, rows)
    cols, rows = _rows(src, "rules", "id")
    _upsert(dst, "rules", "id", cols, rows)
    kept = {r["id"] for r in rows}
    for rule_id in list(dst.execute(text("SELECT id FROM rules")).scalars()):
        if rule_id not in kept:
            dst.execute(text("DELETE FROM rules WHERE id = :i"), {"i": rule_id})
    for table, key in (("debts", "id"), ("debt_balances", "debt_id, on_date")):
        cols, rows = _rows(src, table, key)
        _upsert(dst, table, key, cols, rows)
    cols, rows = _rows(src, "rule_packs", "name")
    _upsert(dst, "rule_packs", "name", cols, rows)
    version = src.execute(text("SELECT version FROM rules_meta")).scalar_one()
    dst.execute(text("UPDATE rules_meta SET version = :v"), {"v": version})
    cols, rows = _rows(src, "fx_rates", "on_date, base, quote, source")
    if rows:
        dst.execute(
            text(
                f"INSERT INTO fx_rates ({', '.join(cols)}) "  # noqa: S608
                f"VALUES ({', '.join(':' + c for c in cols)})"
            ),
            rows,
        )
    fields = hashing.FIELDS["tags"][hashing.current_version("tags")]
    for _seq, *values in src.execute(
        text(f"SELECT rowid, {', '.join(fields)} FROM tags ORDER BY rowid")  # noqa: S608
    ):
        ledger.append(dst, "tags", dict(zip(fields, values, strict=True)))


def _openings(src: Connection, dst: Connection) -> int:
    rows = src.execute(
        text(
            "SELECT account_id, booking_date, amount_minor, currency FROM entries "
            "WHERE kind = 'opening' ORDER BY seq"
        )
    ).fetchall()
    for account_id, on, amount, currency in rows:
        opening.open_account(dst, account_id, on, int(amount), currency)
    return len(rows)


# --- rejeu ----------------------------------------------------------------------------------


def _replay_import(target: Finance, row: Mapping[str, Any], stmts: list[Any]) -> bool:
    """Recrée l'import sous le même identifiant puis l'applique depuis son archive. Un fichier
    refusé ou ignoré (attestation) est recopié tel quel : il n'a rien écrit."""
    service = target.importer
    replay = row["status"] in ("applied", "needs_review", "staged") and bool(stmts)
    with begin_immediate(target.engine()) as conn:
        conn.execute(
            text(
                "INSERT INTO imports (id, source, file_sha256, file_name, received_at, status, "
                "stats_json, archive_path, updated_at) VALUES (:id, :source, :file_sha256, "
                ":file_name, :received_at, :status, :stats_json, :archive_path, :updated_at)"
            ),
            {**row, "status": "staged" if replay else row["status"]},
        )
        if replay:
            for index, opbd, clbd in stmts:
                conn.execute(
                    text(
                        "INSERT INTO import_statements (import_id, stmt_index, opbd_date, "
                        "clbd_date, status, updated_at) VALUES (:i, :x, :o, :c, 'pending', :at)"
                    ),
                    {"i": row["id"], "x": index, "o": opbd, "c": clbd, "at": now_iso()},
                )
    if not replay:
        return False
    staged = service.reread(row["source"], service.archiver.load(row["archive_path"]))
    service.apply_all({row["id"]: staged})
    service.retry_needs_review(quiet=True)
    return True


def _replay_proposal(target: Finance, p: Applied) -> str | None:
    """None si rejouée, sinon le motif de l'abandon."""
    if p.kind in REFERENCE_KINDS:
        return "reference"
    if p.params is None:
        return "params_missing"
    kind = target.proposal_kinds.get(p.kind)
    if kind is None or kind.external:
        return "unknown_kind"
    params = kind.params_model.model_validate(p.params)
    handler: LocalHandler = kind.handler  # type: ignore[assignment]
    try:
        with begin_immediate(target.engine()) as conn:
            result = handler.apply(conn, params, p.proposal_id)
            target.record_applied(conn, p.proposal_id, p.kind, result)
    except Problem:
        return "not_applicable"  # ex. import déjà appliqué tout seul au rejeu
    return None


def rebuild(source: Finance, target: Finance, proposals: list[Applied]) -> RebuildReport:
    report = RebuildReport()
    target.migrate(seed=False)
    target.importer.on_applied = None  # instantanés recalculés une fois, à la fin
    with source.engine().connect() as src:
        head = src.execute(
            text("SELECT chain_hash, epoch FROM journal ORDER BY seq DESC LIMIT 1")
        ).first()
        imports = [
            dict(r._mapping)
            for r in src.execute(
                text(
                    "SELECT id, source, file_sha256, file_name, received_at, status, stats_json, "
                    "archive_path, updated_at FROM imports ORDER BY received_at, id"
                )
            )
        ]
        stmts: dict[str, list[Any]] = {}
        for r in src.execute(
            text(
                "SELECT import_id, stmt_index, opbd_date, clbd_date FROM import_statements "
                "ORDER BY import_id, stmt_index"
            )
        ):
            stmts.setdefault(r[0], []).append((r[1], r[2], r[3]))
        report.epoch = (int(head[1]) if head else 1) + 1
        with begin_immediate(target.engine()) as dst:
            if dst.execute(text("SELECT 1 FROM entries LIMIT 1")).first():
                return RebuildReport(ok=False, error="la base cible n'est pas vide")
            dst.execute(
                text(
                    "INSERT INTO rebuild_meta (id, epoch, source_head, rebuilt_at) "
                    "VALUES (1, :e, :h, :at)"
                ),
                {"e": report.epoch, "h": head[0] if head else hashing.GENESIS, "at": now_iso()},
            )
            copy_reference(src, dst)
            _openings(src, dst)

    work: list[tuple[str, int, Callable[[], None]]] = []
    for row in imports:

        def run_import(row: dict[str, Any] = row) -> None:
            try:
                if _replay_import(target, row, stmts.get(row["id"], [])):
                    report.imports += 1
            except (errors.ImportRefused, secrets.SecretsError, OSError, ViacError) as exc:
                report.ok = False
                report.skip("archive_unavailable")
                log.warning("rebuild.import_failed", import_id=row["id"], error=type(exc).__name__)

        work.append((row["received_at"], 0, run_import))
    for p in proposals:

        def run_proposal(p: Applied = p) -> None:
            reason = _replay_proposal(target, p)
            if reason is None:
                report.proposals += 1
            else:
                report.skip(reason)

        work.append((p.applied_at, 1, run_proposal))
    for _at, _order, step in sorted(work, key=lambda w: (w[0], w[1])):
        step()

    with begin_immediate(target.engine()) as dst:
        rules.run(dst)
    target.refresh_snapshots(force=True)
    if report.skipped.get("params_missing"):
        report.ok = False
    log.info("rebuild.done", **report.public())
    return report


# --- comparaison ----------------------------------------------------------------------------
