"""Service d'import camt.053 (tickets L1-06 et L1-13), section 4 de la spécification.

Réception → validation → analyse → mise en attente → rapprochement → application → archivage.
Les fichiers d'un lot sont appliqués triés par compte puis par date d'OPBD, une transaction par
relevé, jamais par lot. Rien de ce module ne journalise de contenu : des identifiants et des
compteurs seulement.
"""

from __future__ import annotations

import hashlib
import io
import itertools
import json
import re
import time
import zipfile
from collections.abc import Callable, Iterable, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Literal

from sqlalchemy import Connection, Engine, text

from hub.core import canonical, secrets
from hub.core.clock import now_iso, utcnow
from hub.core.db import begin_immediate
from hub.core.ids import new_id, urn
from hub.core.logging import get_logger
from hub.core.text import mask_iban
from hub.domains.finance import catalog, dedup, ledger, rules
from hub.domains.finance.camt import parser
from hub.domains.finance.camt.models import Balance, ParsedEntry, ParsedFile, ParsedStatement

log = get_logger("hub.finance.import")

SOURCE = "camt053"
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
MAX_ZIP_MEMBERS = 500
MAX_ZIP_TOTAL = 200 * 1024 * 1024
SETTLE_SECONDS = 2  # un fichier modifié il y a moins longtemps est peut-être encore en copie
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


class ImportRefused(RuntimeError):
    """Refus d'un import ; `code` est un type d'erreur stable de l'API."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class Incoming:
    name: str
    data: bytes


@dataclass
class FileOutcome:
    name: str
    import_id: str | None
    status: Literal["staged", "duplicate", "rejected"]
    reason: str | None = None


@dataclass
class StatementOutcome:
    import_id: str
    index: int
    status: Literal["applied", "needs_review"]
    reasons: list[str]
    new: int = 0
    duplicates: int = 0


@dataclass
class BatchReport:
    files: list[FileOutcome] = field(default_factory=list)
    statements: list[StatementOutcome] = field(default_factory=list)

    def counters(self) -> dict[str, int]:
        return {
            "files": len(self.files),
            "duplicate_files": sum(f.status == "duplicate" for f in self.files),
            "rejected_files": sum(f.status == "rejected" for f in self.files),
            "statements": len(self.statements),
            "applied": sum(s.status == "applied" for s in self.statements),
            "needs_review": sum(s.status == "needs_review" for s in self.statements),
            "new_entries": sum(s.new for s in self.statements),
            "duplicate_entries": sum(s.duplicates for s in self.statements),
        }


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_name(name: str) -> str:
    return _SAFE_NAME.sub("_", Path(name).name)[:80] or "fichier"


def expand(name: str, data: bytes) -> list[Incoming]:
    """Un .zip devient un fichier par membre .xml, taille décompressée plafonnée."""
    if not name.lower().endswith(".zip"):
        return [Incoming(name, data)]
    out: list[Incoming] = []
    total = 0
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            members = [i for i in z.infolist() if not i.is_dir()]
            if len(members) > MAX_ZIP_MEMBERS:
                raise ImportRefused("import.invalid_schema", "archive zip : trop de fichiers")
            for info in members:
                if not info.filename.lower().endswith(".xml"):
                    continue
                if info.file_size > parser.MAX_BYTES:
                    raise ImportRefused("import.invalid_schema", "archive zip : fichier trop gros")
                with z.open(info) as fh:
                    member = fh.read(parser.MAX_BYTES + 1)
                if len(member) > parser.MAX_BYTES:
                    raise ImportRefused("import.invalid_schema", "archive zip : fichier trop gros")
                total += len(member)
                if total > MAX_ZIP_TOTAL:
                    raise ImportRefused("import.invalid_schema", "archive zip trop volumineuse")
                out.append(Incoming(f"{Path(name).stem}/{Path(info.filename).name}", member))
    except zipfile.BadZipFile as exc:
        raise ImportRefused("import.invalid_schema", "archive zip illisible") from exc
    return out


class Archiver:
    """Chiffre avec age vers archive/AAAA/MM/ ; la clé publique suffit pour écrire."""

    def __init__(self, root: Path, recipient: str | None, identity_file: Path | None) -> None:
        self.root = root
        self.recipient = recipient
        self.identity_file = identity_file

    def store(self, data: bytes, sub: str, name: str) -> str:
        if self.recipient is None:
            raise ImportRefused(
                "import.archive_unavailable", "clé age absente : archivage impossible"
            )
        target = self.root / sub / f"{name}.age"
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".age.tmp")
        tmp.write_bytes(secrets.encrypt_for(self.recipient, data))
        tmp.replace(target)
        return str(target.relative_to(self.root))

    def load(self, relative: str) -> bytes:
        if self.identity_file is None or not self.identity_file.exists():
            raise ImportRefused(
                "import.archive_unavailable", "clé age absente : relecture impossible"
            )
        return secrets.decrypt_with(self.identity_file, (self.root / relative).read_bytes())


def recipient_from_key(key_file: Path) -> str | None:
    if not key_file.exists():
        return None
    return secrets.recipient(key_file)


class ImportService:
    def __init__(
        self,
        engine: Engine,
        *,
        inbox: Path,
        archiver: Archiver,
        lock_file: Path,
        on_applied: Callable[[], object] | None = None,
    ) -> None:
        self.engine = engine
        self.inbox = inbox
        self.archiver = archiver
        self.lock_file = lock_file
        # appelé après un lot dont au moins un relevé est appliqué (instantanés, L2-01)
        self.on_applied = on_applied

    # --- réception -----------------------------------------------------------------------

    def _known(self, digest: str) -> bool:
        with self.engine.connect() as conn:
            row = conn.execute(
                text("SELECT 1 FROM imports WHERE file_sha256 = :h"), {"h": digest}
            ).first()
        return row is not None

    def _record(
        self,
        f: Incoming,
        digest: str,
        status: str,
        stats: dict[str, Any],
        parsed: ParsedFile | None,
    ) -> str:
        import_id = new_id()
        now = now_iso()
        stamp = utcnow().strftime("%Y/%m")
        archive_path = self.archiver.store(f.data, stamp, f"{import_id}-{safe_name(f.name)}")
        with begin_immediate(self.engine) as conn:
            conn.execute(
                text(
                    "INSERT INTO imports (id, source, file_sha256, file_name, received_at, status, "
                    "stats_json, archive_path, updated_at) VALUES (:id, :src, :h, :n, :at, :st, "
                    ":stats, :ap, :at)"
                ),
                {
                    "id": import_id,
                    "src": SOURCE,
                    "h": digest,
                    "n": safe_name(f.name),
                    "at": now,
                    "st": status,
                    "stats": canonical.dumps(stats),
                    "ap": archive_path,
                },
            )
            for s in parsed.statements if parsed else []:
                conn.execute(
                    text(
                        "INSERT INTO import_statements (import_id, stmt_index, opbd_date, "
                        "clbd_date, status, updated_at) VALUES (:i, :x, :o, :c, 'pending', :at)"
                    ),
                    {
                        "i": import_id,
                        "x": s.index,
                        "o": s.opening.on_date if s.opening else None,
                        "c": s.closing.on_date if s.closing else None,
                        "at": now,
                    },
                )
        return import_id

    def stage(self, f: Incoming) -> tuple[FileOutcome, ParsedFile | None]:
        digest = sha256(f.data)
        if self._known(digest):
            self.archiver.store(f.data, "duplicates", f"{digest[:16]}-{safe_name(f.name)}")
            log.info("import.duplicate_file")
            return FileOutcome(f.name, None, "duplicate", "import.duplicate_file"), None
        try:
            parsed = parser.parse(f.data)
        except parser.CamtError as exc:
            stats: dict[str, Any] = {"reason": exc.code, "detail": exc.reason}
            import_id = self._record(f, digest, "rejected", stats, None)
            log.warning("import.rejected", import_id=import_id, reason=exc.code)
            return FileOutcome(f.name, import_id, "rejected", exc.code), None
        stats = {"version": parsed.version}
        import_id = self._record(f, digest, "staged", stats, parsed)
        return FileOutcome(f.name, import_id, "staged"), parsed

    # --- rapprochement et application ----------------------------------------------------

    def apply_all(
        self, staged: dict[str, ParsedFile], only: set[tuple[str, int]] | None = None
    ) -> list[StatementOutcome]:
        """Applique les relevés triés par compte puis par OPBD, une transaction chacun."""
        work = [
            (import_id, s)
            for import_id, pf in staged.items()
            for s in pf.statements
            if only is None or (import_id, s.index) in only
        ]
        work.sort(
            key=lambda w: (w[1].iban or "", w[1].opening.on_date if w[1].opening else "", w[0])
        )
        outcomes = [self._apply_statement(import_id, s) for import_id, s in work]
        for import_id in sorted({o.import_id for o in outcomes}):
            self._finish(import_id)
        if self.on_applied and any(o.status == "applied" for o in outcomes):
            try:
                self.on_applied()
            except Exception as exc:  # l'import est fait ; la tâche de nuit rattrapera
                log.warning("import.after_apply_failed", error=type(exc).__name__)
        return outcomes

    def _apply_statement(self, import_id: str, st: ParsedStatement) -> StatementOutcome:
        with begin_immediate(self.engine) as conn:
            result = apply_statement(conn, import_id, st)
        log.info(
            "import.statement",
            import_id=import_id,
            stmt=st.index,
            status=result.status,
            reasons=result.reasons,
            new=result.new,
            duplicates=result.duplicates,
        )
        return result

    def _finish(self, import_id: str) -> None:
        with begin_immediate(self.engine) as conn:
            finish(conn, import_id)

    # --- boîte d'entrée ------------------------------------------------------------------

    def ready_files(self) -> list[Path]:
        if not self.inbox.is_dir():
            return []
        now = time.time()
        out = []
        for p in sorted(self.inbox.iterdir()):
            if not p.is_file() or p.name.startswith("."):
                continue
            if p.suffix.lower() not in {".xml", ".zip"}:
                continue
            if now - p.stat().st_mtime < SETTLE_SECONDS:
                continue
            out.append(p)
        return out

    def process(self, files: Iterable[Incoming]) -> BatchReport:
        report = BatchReport()
        staged: dict[str, ParsedFile] = {}
        for raw in files:
            try:
                members = expand(raw.name, raw.data)
            except ImportRefused as exc:
                members = []
                report.files.append(FileOutcome(raw.name, None, "rejected", exc.code))
            for f in members:
                outcome, parsed = self.stage(f)
                report.files.append(outcome)
                if parsed is not None and outcome.import_id is not None:
                    staged[outcome.import_id] = parsed
        report.statements = self.apply_all(staged)
        if any(s.status == "applied" and s.new for s in report.statements):
            report.statements += self.retry_needs_review(quiet=True)
        return report

    def process_inbox(self) -> BatchReport:
        """Traite l'inbox jusqu'à ce qu'elle soit vide ; rien pendant une reprise d'historique."""
        total = BatchReport()
        if self.lock_file.exists():
            log.info("import.paused", reason="history")
            return total
        while paths := self.ready_files():
            incoming = [Incoming(p.name, p.read_bytes()) for p in paths]
            batch = self.process(incoming)
            for p in paths:
                p.unlink()
            total.files += batch.files
            total.statements += batch.statements
        return total

    def receive(self, name: str, data: bytes) -> BatchReport:
        """POST /api/finance/imports : même traitement que l'inbox."""
        if self.lock_file.exists():
            raise ImportRefused("busy.retry", "reprise d'historique en cours")
        return self.process([Incoming(name, data)])

    def parsed(self, conn: Connection, import_id: str) -> ParsedFile:
        """Relit un import depuis son archive chiffrée."""
        row = conn.execute(
            text("SELECT archive_path FROM imports WHERE id = :i"), {"i": import_id}
        ).first()
        if row is None or not row[0]:
            raise ImportRefused("import.not_found", "import inconnu")
        try:
            return parser.parse(self.archiver.load(row[0]))
        except (secrets.SecretsError, OSError) as exc:
            raise ImportRefused("import.archive_unavailable", "archive illisible") from exc

    def review_plan(self, conn: Connection, import_id: str) -> list[tuple[int, Plan]]:
        """Relevés en attente d'un import et ce que leur validation écrirait (lecture seule)."""
        waiting = set(
            conn.execute(
                text(
                    "SELECT stmt_index FROM import_statements WHERE import_id = :i "
                    "AND status = 'needs_review'"
                ),
                {"i": import_id},
            ).scalars()
        )
        if not waiting:
            return []
        pf = self.parsed(conn, import_id)
        return [(st.index, plan_statement(conn, st)) for st in pf.statements if st.index in waiting]

    def force(self, conn: Connection, import_id: str, proposal_id: str) -> list[StatementOutcome]:
        """`apply_import` validé : applique les relevés en attente malgré les anomalies
        acceptables, dans la transaction de l'appelant."""
        waiting = {i for i, _ in self.review_plan(conn, import_id)}
        pf = self.parsed(conn, import_id)
        outcomes = [
            apply_statement(conn, import_id, st, force=True, proposal_id=proposal_id)
            for st in pf.statements
            if st.index in waiting
        ]
        finish(conn, import_id)
        return outcomes

    def retry_needs_review(
        self, import_ids: Sequence[str] | None = None, *, quiet: bool = False
    ) -> list[StatementOutcome]:
        """Rejoue les relevés en attente depuis l'archive chiffrée (après une ouverture, un
        compte ajouté ou un relevé manquant arrivé entre-temps)."""
        with self.engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT s.import_id, s.stmt_index, i.archive_path FROM import_statements s "
                    "JOIN imports i ON i.id = s.import_id WHERE s.status = 'needs_review' "
                    "ORDER BY i.received_at"
                )
            ).fetchall()
        wanted = [r for r in rows if import_ids is None or r[0] in import_ids]
        if not wanted:
            return []
        staged: dict[str, ParsedFile] = {}
        only = set()
        for import_id, index, archive_path in wanted:
            if import_id not in staged:
                try:
                    staged[import_id] = parser.parse(self.archiver.load(archive_path))
                except (ImportRefused, secrets.SecretsError, OSError) as exc:
                    if quiet:
                        log.warning("import.retry_unavailable", error=type(exc).__name__)
                        return []
                    if isinstance(exc, ImportRefused):
                        raise
                    raise ImportRefused("import.archive_unavailable", "archive illisible") from exc
            only.add((import_id, index))
        return self.apply_all(staged, only)


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

    iban = account.iban or ""
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
    if st.opening is not None and st.closing is not None:
        total = st.opening.amount_minor + sum(e.amount_minor for e in st.entries)
        if total != st.closing.amount_minor:
            reasons.append("internal_check_failed")
        for kind, bal in (("OPBD", st.opening), ("CLBD", st.closing)):
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
            conn,
            "import.applied",
            target,
            {"new": stats["new"], "duplicates": stats["duplicates"]},
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


# --- ouverture et reprise d'historique ------------------------------------------------------


def open_account(
    conn: Connection, account_id: str, booking_date: str, amount_minor: int, currency: str
) -> int:
    """Écriture d'ouverture, une seule par compte. Sa clé vient de l'IBAN (ou de la référence
    externe), pas du ULID du compte : une reconstruction redonne le même identifiant."""
    account = catalog.get_account(conn, account_id)
    if conn.execute(
        text("SELECT 1 FROM entries WHERE account_id = :a LIMIT 1"), {"a": account_id}
    ).first():
        raise ImportRefused("import.before_opening", "le registre de ce compte est déjà ouvert")
    seq, _ = ledger.append_entry(
        conn,
        ledger.NewEntry(
            account_id=account_id,
            kind="opening",
            booking_date=booking_date,
            amount_minor=amount_minor,
            currency=currency,
            dedup_key=dedup.opening_key(account.iban or account.external_ref or account.id),
            label="Solde d'ouverture",
        ),
    )
    return seq


@dataclass
class HistoryReport:
    ok: bool
    accounts: list[dict[str, Any]] = field(default_factory=list)
    batch: dict[str, int] = field(default_factory=dict)
    error: str | None = None
    missing: list[dict[str, str]] = field(default_factory=list)  # périodes manquantes

    def public(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "error": self.error,
            "missing": self.missing,
            "accounts": self.accounts,
            "batch": self.batch,
        }


@contextmanager
def _locked(lock_file: Path) -> Any:
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        lock_file.touch(exist_ok=False)
    except FileExistsError:
        raise ImportRefused("busy.retry", "une reprise d'historique est déjà en cours") from None
    try:
        yield
    finally:
        lock_file.unlink(missing_ok=True)


def _day_before(iso_date: str) -> str:
    return (date.fromisoformat(iso_date) - timedelta(days=1)).isoformat()


def import_history(service: ImportService, folder: Path) -> HistoryReport:
    """`hub finance import-history <dossier>` : trie, vérifie la continuité avant d'écrire, ouvre
    chaque compte au relevé le plus ancien, puis applique tout. Un trou arrête tout."""
    with _locked(service.lock_file):
        files: dict[str, Incoming] = {}
        for p in sorted(folder.iterdir()):
            if p.is_file() and p.suffix.lower() in {".xml", ".zip"}:
                for f in expand(p.name, p.read_bytes()):
                    files.setdefault(sha256(f.data), f)
        parsed: list[tuple[Incoming, ParsedFile]] = []
        for f in files.values():
            if service._known(sha256(f.data)):
                continue
            try:
                parsed.append((f, parser.parse(f.data)))
            except parser.CamtError as exc:
                return HistoryReport(ok=False, error=f"{exc.code} : {safe_name(f.name)}")

        by_iban: dict[str, list[_Span]] = {}
        for _f, pf in parsed:
            for s in pf.statements:
                if s.iban is None or s.opening is None or s.closing is None:
                    return HistoryReport(ok=False, error="relevé sans IBAN ou sans soldes")
                by_iban.setdefault(s.iban, []).append(_Span(s, s.opening, s.closing))

        report = HistoryReport(ok=True)
        openings: list[tuple[catalog.Account, _Span]] = []
        with service.engine.connect() as conn:
            for iban, spans in sorted(by_iban.items()):
                account = catalog.account_by_iban(conn, iban)
                if account is None:
                    return HistoryReport(ok=False, error=f"compte inconnu : {mask_iban(iban)}")
                if conn.execute(
                    text("SELECT 1 FROM entries WHERE account_id = :a LIMIT 1"), {"a": account.id}
                ).first():
                    return HistoryReport(
                        ok=False, error=f"registre déjà ouvert pour {mask_iban(iban)}"
                    )
                spans.sort(key=lambda x: (x.opening.on_date, x.closing.on_date))
                for prev, nxt in itertools.pairwise(spans):
                    # CLBD d'un relevé = OPBD du suivant ; deux relevés qui se recouvrent sont
                    # laissés au dédoublonnage
                    overlap = nxt.opening.on_date <= prev.closing.on_date
                    if not overlap and nxt.opening.amount_minor != prev.closing.amount_minor:
                        report.missing.append(
                            {
                                "account": mask_iban(iban) or "",
                                "from": prev.closing.on_date,
                                "to": nxt.opening.on_date,
                            }
                        )
                openings.append((account, spans[0]))
        if report.missing:
            report.ok = False
            report.error = "historique discontinu"
            return report

        for account, oldest in openings:
            first = min([e.booking_date for e in oldest.stmt.entries] + [oldest.opening.on_date])
            with begin_immediate(service.engine) as conn:
                open_account(
                    conn,
                    account.id,
                    _day_before(first),
                    oldest.opening.amount_minor,
                    account.currency,
                )
        batch = service.process(f for f, _ in parsed)
        report.batch = batch.counters()
        report.ok = report.batch["needs_review"] == 0 and report.batch["rejected_files"] == 0
        with service.engine.connect() as conn:
            for account, _oldest in openings:
                row = conn.execute(
                    text(
                        "SELECT count(*), min(booking_date), max(booking_date) FROM entries "
                        "WHERE account_id = :a AND kind = 'movement'"
                    ),
                    {"a": account.id},
                ).one()
                report.accounts.append(
                    {
                        "account": mask_iban(account.iban),
                        "statements": len(by_iban[account.iban or ""]),
                        "entries": row[0],
                        "from": row[1],
                        "to": row[2],
                    }
                )
        return report


@dataclass(frozen=True)
class _Span:
    stmt: ParsedStatement
    opening: Balance
    closing: Balance
