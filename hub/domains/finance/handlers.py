"""Types de proposition du domaine Finance (ticket L3-02, section 5 de la spécification).

Chaque handler a un aperçu en lecture seule, dont l'empreinte couvre exactement ce que l'effet
va toucher, et un `apply()` appelé dans la transaction `BEGIN IMMEDIATE` ouverte par le cœur.
Le cœur compare l'empreinte relue sous verrou à celle de la carte validée : si elle a changé,
la carte passe à la révision suivante au lieu de s'appliquer.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, timedelta
from typing import TYPE_CHECKING, Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import Connection, text

from hub.core import canonical
from hub.core.clock import now_iso
from hub.core.domain import Preview, ProposalKind
from hub.core.errors import Problem
from hub.core.ids import new_id
from hub.core.money import Money, base_currency
from hub.core.text import mask_iban, normalize
from hub.domains.finance import catalog, importer, ledger, packs, period, rules

if TYPE_CHECKING:
    from hub.domains.finance.domain import FinanceDomain

SAMPLE = 10  # écritures montrées dans un aperçu ; les totaux portent sur toutes
# à priorité égale, l'identifiant départage : « user- » trie après « legacy- », « seed- » et
# « system- », et un ULID plus récent après les plus anciens. Une règle créée perd donc les ex
# aequo, dans l'aperçu (« ~ » trie après tout ULID) comme une fois appliquée.
USER_RULE_PREFIX = "user-"
PREVIEW_RULE_ID = f"{USER_RULE_PREFIX}~"
Slug = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9-]{1,40}$")]
EntryId = Annotated[str, Field(min_length=2, max_length=40, pattern=r"^e[0-9a-f]+$")]


class _Params(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _fp(*parts: object) -> str:
    return canonical.sha256_hex(list(parts))


def _bad(detail: str) -> Problem:
    return Problem("validation.params", detail)


def _display(minor: int, currency: str) -> str:
    return f"{Money(minor, currency).display()} {currency}"


def _category(conn: Connection, category_id: str) -> tuple[str, str]:
    row = conn.execute(
        text("SELECT name, grp, active FROM categories WHERE id = :c"), {"c": category_id}
    ).first()
    if row is None or not row[2]:
        raise _bad(f"catégorie inconnue ou inactive : {category_id}")
    return str(row[0]), str(row[1])


def _entry_brief(r: Any) -> dict[str, Any]:
    return {
        "id": r.id,
        "booking_date": r.booking_date,
        "amount": Money(int(r.amount_minor), r.currency).to_api(),
        "counterparty": ledger.party(r.counterparty) or r.label or None,
    }


def _entry(conn: Connection, entry_id: str) -> Any:
    row = conn.execute(
        text(
            "SELECT e.seq, e.id, e.kind, e.booking_date, e.amount_minor, e.currency, "
            "e.counterparty, e.label, vc.category_id, vc.categorization_seq "
            "FROM entries e LEFT JOIN v_entry_category vc ON vc.entry_seq = e.seq "
            "WHERE e.id = :i"
        ),
        {"i": entry_id},
    ).first()
    if row is None:
        raise _bad("écriture inconnue")
    return row


def _totals(items: list[tuple[int, str]]) -> list[dict[str, Any]]:
    sums: dict[str, int] = {}
    for minor, ccy in items:
        sums[ccy] = sums.get(ccy, 0) + minor
    return [Money(v, k).to_api() for k, v in sorted(sums.items())]


# --- recategorize ---------------------------------------------------------------------------


class Line(_Params):
    category_id: Slug
    amount_minor: int


class Recategorize(_Params):
    entry_id: EntryId
    category_id: Slug
    lines: list[Line] | None = Field(default=None, min_length=2, max_length=20)
    suggested: bool = False  # proposée par un modèle et acceptée telle quelle


class RecategorizeHandler:
    def preview(self, conn: Connection, params: BaseModel) -> Preview:
        assert isinstance(params, Recategorize)  # noqa: S101
        e = _entry(conn, params.entry_id)
        if e.kind != "movement":
            raise _bad("seules les écritures de mouvement se catégorisent")
        name, _grp = _category(conn, params.category_id)
        if params.lines is not None:
            for line in params.lines:
                _category(conn, line.category_id)
                if line.amount_minor == 0 or (line.amount_minor < 0) != (e.amount_minor < 0):
                    raise _bad("chaque ligne a le signe de l'écriture et n'est pas nulle")
            if sum(x.amount_minor for x in params.lines) != e.amount_minor:
                raise _bad("la ventilation doit sommer au montant de l'écriture")
        before = e.category_id
        split = f", ventilée en {len(params.lines)}" if params.lines else ""
        return Preview(
            summary=f"1 écriture → {name}{split} ({_display(e.amount_minor, e.currency)})",
            details={
                "entries": [_entry_brief(e)],
                "count": 1,
                "from_category": before,
                "to_category": params.category_id,
                "lines": [x.model_dump() for x in params.lines] if params.lines else None,
            },
            fingerprint=_fp("recategorize", e.id, e.categorization_seq or 0),
        )

    def apply(self, conn: Connection, params: BaseModel, proposal_id: str) -> dict[str, Any]:
        assert isinstance(params, Recategorize)  # noqa: S101
        e = _entry(conn, params.entry_id)
        seq = ledger.append(
            conn,
            "categorizations",
            {
                "entry_seq": e.seq,
                "category_id": params.category_id,
                "source": "suggestion_accepted" if params.suggested else "user",
                "rule_id": None,
                "proposal_id": proposal_id,
                "created_at": now_iso(),
            },
        )
        for i, line in enumerate(params.lines or []):
            ledger.append(
                conn,
                "categorization_lines",
                {
                    "categorization_seq": seq,
                    "line": i,
                    "category_id": line.category_id,
                    "amount_minor": line.amount_minor,
                },
            )
        return {
            "entry_id": e.id,
            "categorization_seq": seq,
            "previous_category": e.category_id,
        }


def _recategorize_inverse(
    params: dict[str, Any], result: dict[str, Any]
) -> tuple[str, dict[str, Any]]:
    previous = result.get("previous_category")
    if previous is None:
        raise ValueError("l'écriture n'avait pas de catégorie")
    return "recategorize", {"entry_id": params["entry_id"], "category_id": previous}


# --- tout le reste d'avant une date ---------------------------------------------------------

REST_MAX = 5000


class CategorizeRest(_Params):
    """Classe d'un coup les écritures encore sans catégorie d'avant une date (le vieil
    historique, souvent des achats uniques qu'on ne classera jamais un par un)."""

    before: date
    direction: Literal["debit", "credit"] = "debit"
    category_id: Slug


def _rest(conn: Connection, params: CategorizeRest) -> list[Any]:
    sign = "<" if params.direction == "debit" else ">"
    return list(
        conn.execute(
            text(
                "SELECT e.seq, e.id, e.booking_date, e.amount_minor, e.currency, e.counterparty, "
                "e.label FROM entries e LEFT JOIN v_entry_shown vc ON vc.entry_seq = e.seq "
                "WHERE vc.category_id IS NULL AND e.kind = 'movement' AND e.booking_date < :d "
                f"AND e.amount_minor {sign} 0 ORDER BY e.booking_date DESC, e.seq DESC LIMIT :n"
            ),
            {"d": params.before.isoformat(), "n": REST_MAX + 1},
        ).fetchall()
    )


class CategorizeRestHandler:
    def preview(self, conn: Connection, params: BaseModel) -> Preview:
        assert isinstance(params, CategorizeRest)  # noqa: S101
        name, _grp = _category(conn, params.category_id)
        rows = _rest(conn, params)
        if len(rows) > REST_MAX:
            raise _bad(f"plus de {REST_MAX} écritures : choisis une date plus ancienne")
        if not rows:
            raise _bad("aucune écriture sans catégorie avant cette date")
        sens = "dépense" if params.direction == "debit" else "entrée"
        n = len(rows)
        return Preview(
            summary=(
                f"{n} {sens}{'s' if n > 1 else ''} sans catégorie d'avant le "
                f"{params.before.strftime('%d.%m.%Y')} → {name}"
            ),
            details={
                "count": n,
                "totals": _totals([(int(r.amount_minor), r.currency) for r in rows]),
                "entries": [_entry_brief(r) for r in rows[:SAMPLE]],
                "to_category": params.category_id,
            },
            fingerprint=_fp("categorize_rest", sorted(r.id for r in rows)),
        )

    def apply(self, conn: Connection, params: BaseModel, proposal_id: str) -> dict[str, Any]:
        assert isinstance(params, CategorizeRest)  # noqa: S101
        rows = _rest(conn, params)
        at = now_iso()
        for r in rows:
            ledger.append(
                conn,
                "categorizations",
                {
                    "entry_seq": r.seq,
                    "category_id": params.category_id,
                    "source": "user",
                    "rule_id": None,
                    "proposal_id": proposal_id,
                    "created_at": at,
                },
            )
        return {"changed": len(rows)}


# --- règles ---------------------------------------------------------------------------------


class CreateRule(_Params):
    field: Literal["search_text", "counterparty_iban", "bank_tx_code"] = "search_text"
    pattern: str = Field(max_length=120)
    direction: Literal["any", "debit", "credit"] = "any"
    category_id: Slug
    priority: int = Field(default=50, ge=1, le=10_000)
    # règle d'un seul compte ; son motif peut être vide : « tout débit de ce compte »
    account_id: str | None = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def _pattern(self) -> CreateRule:
        try:
            value = rules.normalize_pattern(self.field, self.pattern)
        except rules.RuleError as exc:
            raise ValueError(str(exc)) from None
        short = self.field == "search_text" and len(value.strip()) < 2
        if short and (self.account_id is None or value.strip()):
            raise ValueError("motif de deux caractères au moins")
        return self

    def normalized(self) -> str:
        return rules.normalize_pattern(self.field, self.pattern)


class CreateRuleHandler:
    def _rule(self, params: CreateRule, rule_id: str = "new") -> rules.Rule:
        return rules.Rule(
            rule_id,
            params.field,
            params.normalized(),
            params.direction,
            params.category_id,
            params.priority,
            account_id=params.account_id,
        )

    def _changes(self, conn: Connection, params: CreateRule, rule_id: str) -> list[rules.Change]:
        rule = self._rule(params, rule_id)
        current = rules.load(conn)
        return rules.changes(current.with_rule(rule), rules.candidates(conn), only=rule)

    def preview(self, conn: Connection, params: BaseModel) -> Preview:
        assert isinstance(params, CreateRule)  # noqa: S101
        name, _grp = _category(conn, params.category_id)
        account = None
        if params.account_id is not None:
            account = conn.execute(
                text("SELECT name FROM accounts WHERE id = :i"), {"i": params.account_id}
            ).scalar()
            if account is None:
                raise _bad(f"compte inconnu : {params.account_id}")
        found = self._changes(conn, params, PREVIEW_RULE_ID)
        items = [(c.current.amount_minor, c.current.currency) for c in found]
        sample = _sample(conn, [c.current.entry_seq for c in found[:SAMPLE]])
        shape = {"search_text": "texte", "counterparty_iban": "IBAN", "bank_tx_code": "code"}
        motif = mask_iban(params.normalized()) if params.field == "counterparty_iban" else None
        what = f"{shape[params.field]} « {motif or params.normalized().strip()} »"
        if account is not None:
            sens = {"debit": "débit", "credit": "crédit", "any": "mouvement"}[params.direction]
            what = (
                f"« {account} » : {f'{what}, ' if params.normalized().strip() else ''}tout {sens}"
            )
        return Preview(
            summary=f"Règle {what} → {name} : {len(found)} écriture{'s' if len(found) > 1 else ''}",
            details={
                "count": len(found),
                "totals": _totals(items),
                "entries": sample,
                "to_category": params.category_id,
                "rules_version": rules.version(conn),
            },
            # les écritures touchées et leur état, pas la version globale des règles : une autre
            # règle validée dans le même lot (un autre commerçant) ne rend pas celle-ci périmée
            fingerprint=_fp(
                "create_rule",
                sorted((c.current.entry_id, c.current.categorization_seq or 0) for c in found),
            ),
        )

    def apply(self, conn: Connection, params: BaseModel, proposal_id: str) -> dict[str, Any]:
        assert isinstance(params, CreateRule)  # noqa: S101
        rule_id = f"{USER_RULE_PREFIX}{new_id()}"
        found = self._changes(conn, params, rule_id)
        rule = rules.insert_rule(
            conn,
            id=rule_id,
            field=params.field,
            pattern=params.normalized(),
            direction=params.direction,
            category_id=params.category_id,
            priority=params.priority,
            proposal_id=proposal_id,
            account_id=params.account_id,
        )
        version = rules.bump_version(conn)
        changed = rules.apply_changes(
            conn, [rules.Change(c.current, rule) for c in found], proposal_id
        )
        return {"rule_id": rule.id, "changed": changed, "rules_version": version}


def _sample(conn: Connection, seqs: list[int]) -> list[dict[str, Any]]:
    if not seqs:
        return []
    marks = ",".join(f":s{i}" for i in range(len(seqs)))
    sql = (
        "SELECT id, booking_date, amount_minor, currency, counterparty, label FROM entries "
        f"WHERE seq IN ({marks}) ORDER BY booking_date DESC"
    )
    rows = conn.execute(
        text(sql),
        {f"s{i}": s for i, s in enumerate(seqs)},
    ).fetchall()
    return [_entry_brief(r) for r in rows]


class DisableRule(_Params):
    rule_id: str = Field(min_length=3, max_length=60)


class DisableRuleHandler:
    def preview(self, conn: Connection, params: BaseModel) -> Preview:
        assert isinstance(params, DisableRule)  # noqa: S101
        rule = rules.get_rule(conn, params.rule_id)
        if rule is None or not rule.active:
            raise _bad("règle inconnue ou déjà désactivée")
        if rule.id.startswith(rules.SYSTEM_PREFIX):
            raise _bad("une règle système ne se désactive pas")
        name, _ = _category(conn, rule.category_id)
        used = conn.execute(
            text("SELECT count(*) FROM categorizations WHERE rule_id = :r"), {"r": rule.id}
        ).scalar_one()
        return Preview(
            summary=f"Désactiver la règle « {rule.pattern.strip() or '*'} » → {name}",
            details={"rule_id": rule.id, "categorizations_kept": int(used)},
            fingerprint=_fp("disable_rule", rules.version(conn), rule.id),
        )

    def apply(self, conn: Connection, params: BaseModel, proposal_id: str) -> dict[str, Any]:
        assert isinstance(params, DisableRule)  # noqa: S101
        rules.set_active(conn, params.rule_id, False)
        return {"rule_id": params.rule_id, "rules_version": rules.bump_version(conn)}


# --- budget et notes ------------------------------------------------------------------------


class SetBudget(_Params):
    category_id: Slug
    monthly_minor: int = Field(ge=0, le=100_000_000)
    currency: str = Field(default_factory=base_currency)
    valid_from: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-01$")
    # suivi au mois ou à l'année (cible annuelle = 12 × monthly_minor) ; absent : inchangé
    cadence: Literal["month", "year"] | None = None

    @field_validator("currency")
    @classmethod
    def _base(cls, value: str) -> str:
        if value != base_currency():
            raise ValueError("un budget est dans la devise de base de l'instance")
        return value


def _budget_row(conn: Connection, category_id: str) -> Any:
    return conn.execute(
        text(
            "SELECT seq, monthly_minor FROM budgets WHERE category_id = :c "
            "ORDER BY seq DESC LIMIT 1"
        ),
        {"c": category_id},
    ).first()


class SetBudgetHandler:
    def __init__(self, domain: FinanceDomain) -> None:
        self.domain = domain

    def _from(self, params: SetBudget) -> str:
        return params.valid_from or f"{period.month_of(self.domain.today())}-01"

    def preview(self, conn: Connection, params: BaseModel) -> Preview:
        assert isinstance(params, SetBudget)  # noqa: S101
        name, grp = _category(conn, params.category_id)
        if grp not in ("fixed", "variable"):
            raise _bad("un budget porte sur une catégorie de dépenses")
        current = _budget_row(conn, params.category_id)
        before = int(current.monthly_minor) if current else None
        cadence = params.cadence or _cadence(conn, params.category_id)
        if cadence == "year":
            then = (
                f" (avant {_display(before * 12, params.currency)})" if before is not None else ""
            )
            amount = f"{_display(params.monthly_minor * 12, params.currency)} par an"
        else:
            then = f" (avant {_display(before, params.currency)})" if before is not None else ""
            amount = f"{_display(params.monthly_minor, params.currency)} par mois"
        return Preview(
            summary=f"Budget {name} : {amount}{then}, dès {self._from(params)[:7]}",
            details={
                "category_id": params.category_id,
                "monthly": Money(params.monthly_minor, params.currency).to_api(),
                "previous": Money(before, params.currency).to_api() if before is not None else None,
                "valid_from": self._from(params),
                "cadence": cadence,
            },
            fingerprint=_fp("set_budget", params.category_id, current.seq if current else 0),
        )

    def apply(self, conn: Connection, params: BaseModel, proposal_id: str) -> dict[str, Any]:
        assert isinstance(params, SetBudget)  # noqa: S101
        current = _budget_row(conn, params.category_id)
        seq = ledger.append(
            conn,
            "budgets",
            {
                "category_id": params.category_id,
                "monthly_minor": params.monthly_minor,
                "currency": params.currency,
                "valid_from": self._from(params),
                "proposal_id": proposal_id,
                "created_at": now_iso(),
            },
        )
        before = _cadence(conn, params.category_id)
        if params.cadence is not None and params.cadence != before:
            conn.execute(
                text(
                    "INSERT INTO budget_cadence (category_id, cadence, updated_at, actor) "
                    "VALUES (:c, :k, :at, :p) ON CONFLICT (category_id) DO UPDATE SET "
                    "cadence = excluded.cadence, updated_at = excluded.updated_at, "
                    "actor = excluded.actor"
                ),
                {"c": params.category_id, "k": params.cadence, "at": now_iso(), "p": proposal_id},
            )
        return {
            "budget_seq": seq,
            "previous_minor": int(current.monthly_minor) if current else None,
            "previous_cadence": before,
            "valid_from": self._from(params),
        }


def _budget_inverse(params: dict[str, Any], result: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    previous = result.get("previous_minor")
    return "set_budget", {
        "category_id": params["category_id"],
        "monthly_minor": 0 if previous is None else previous,
        "currency": params.get("currency") or base_currency(),
        "valid_from": result.get("valid_from"),
        "cadence": result.get("previous_cadence") or "month",
    }


def _cadence(conn: Connection, category_id: str) -> str:
    row = conn.execute(
        text("SELECT cadence FROM budget_cadence WHERE category_id = :c"), {"c": category_id}
    ).first()
    return str(row[0]) if row else "month"


class AddNote(_Params):
    entry_id: EntryId
    text: str = Field(min_length=1, max_length=1000)


class AddNoteHandler:
    def _last(self, conn: Connection, entry_seq: int) -> int:
        return int(
            conn.execute(
                text("SELECT coalesce(max(seq), 0) FROM notes WHERE entry_seq = :e"),
                {"e": entry_seq},
            ).scalar_one()
        )

    def preview(self, conn: Connection, params: BaseModel) -> Preview:
        assert isinstance(params, AddNote)  # noqa: S101
        e = _entry(conn, params.entry_id)
        return Preview(
            summary=f"Note sur 1 écriture ({_display(e.amount_minor, e.currency)})",
            details={"entries": [_entry_brief(e)], "text": params.text},
            fingerprint=_fp("add_note", e.id, self._last(conn, e.seq)),
        )

    def apply(self, conn: Connection, params: BaseModel, proposal_id: str) -> dict[str, Any]:
        assert isinstance(params, AddNote)  # noqa: S101
        e = _entry(conn, params.entry_id)
        seq = ledger.append(
            conn,
            "notes",
            {
                "entry_seq": e.seq,
                "text": params.text,
                "search_text": normalize(params.text),
                "proposal_id": proposal_id,
                "created_at": now_iso(),
            },
        )
        return {"entry_id": e.id, "note_seq": seq}


# --- import, comptes, catégories -------------------------------------------------------------


class ApplyImport(_Params):
    import_id: str = Field(min_length=10, max_length=40)


class ApplyImportHandler:
    def __init__(self, domain: FinanceDomain) -> None:
        self.domain = domain

    def preview(self, conn: Connection, params: BaseModel) -> Preview:
        assert isinstance(params, ApplyImport)  # noqa: S101
        status = conn.execute(
            text("SELECT status FROM imports WHERE id = :i"), {"i": params.import_id}
        ).scalar_one_or_none()
        if status is None:
            raise Problem("import.not_found")
        if status != "needs_review":
            raise Problem("import.not_applicable", f"import {status}")
        try:
            plans = self.domain.importer.review_plan(conn, params.import_id)
        except importer.ImportRefused as exc:
            raise Problem(exc.code, exc.detail) from None
        blocking = sorted({r for _, p in plans for r in p.blocking})
        if not plans or blocking:
            raise Problem("import.not_applicable", ",".join(blocking) or "rien à valider")
        keys = sorted(k for _, p in plans for _e, k in p.fresh)
        items = [(e.amount_minor, e.currency) for _, p in plans for e, _k in p.fresh]
        reasons = sorted({r for _, p in plans for r in p.reasons})
        return Preview(
            summary=f"Valider l'import malgré : {', '.join(reasons)} — {len(keys)} écriture"
            f"{'s' if len(keys) > 1 else ''} à ajouter",
            details={
                "import_id": params.import_id,
                "reasons": reasons,
                "statements": [
                    {
                        "index": i,
                        "account": p.account.name if p.account else None,
                        "reasons": p.reasons,
                        "new": len(p.fresh),
                        "duplicates": p.duplicates,
                    }
                    for i, p in plans
                ],
                "count": len(keys),
                "totals": _totals(items),
            },
            fingerprint=_fp("apply_import", status, keys),
        )

    def apply(self, conn: Connection, params: BaseModel, proposal_id: str) -> dict[str, Any]:
        assert isinstance(params, ApplyImport)  # noqa: S101
        try:
            outcomes = self.domain.importer.force(conn, params.import_id, proposal_id)
        except importer.ImportRefused as exc:
            raise Problem(exc.code, exc.detail) from None
        return {
            "import_id": params.import_id,
            "statements": len(outcomes),
            "new": sum(o.new for o in outcomes),
        }

    def after_commit(self, params: BaseModel, result: dict[str, Any]) -> None:
        self.domain.refresh_snapshots()


class CreateAccount(_Params):
    institution: str = Field(min_length=2, max_length=40)
    name: str = Field(min_length=1, max_length=80)
    kind: Literal["cash", "securities", "pension", "crypto"] = "cash"
    currency: str = Field(default_factory=base_currency, pattern=r"^[A-Z]{3}$")
    iban: str | None = Field(default=None, max_length=40)
    external_ref: str | None = Field(default=None, max_length=80)
    liquid: bool = False
    budget_account: bool = False


class CreateAccountHandler:
    def __init__(self, domain: FinanceDomain) -> None:
        self.domain = domain

    def preview(self, conn: Connection, params: BaseModel) -> Preview:
        assert isinstance(params, CreateAccount)  # noqa: S101
        if params.iban is None and params.external_ref is None:
            raise _bad("un compte a un IBAN ou une référence externe")
        if params.iban is not None and catalog.account_by_iban(conn, params.iban):
            raise _bad("compte déjà connu")
        if (
            params.external_ref is not None
            and conn.execute(
                text("SELECT 1 FROM accounts WHERE external_ref = :r"), {"r": params.external_ref}
            ).first()
        ):
            raise _bad("compte déjà connu")
        waiting = 0
        if params.iban is not None:
            waiting = len(self._waiting(conn))
        ref = mask_iban(params.iban) or params.external_ref
        return Preview(
            summary=f"Nouveau compte {params.institution} « {params.name} » ({ref})"
            + (f", {waiting} relevé(s) en attente relancé(s)" if waiting else ""),
            details={
                "institution": params.institution,
                "name": params.name,
                "kind": params.kind,
                "currency": params.currency,
                "iban": mask_iban(params.iban),
                "waiting_statements": waiting,
            },
            fingerprint=_fp("create_account", "absent", params.iban, params.external_ref),
        )

    def _waiting(self, conn: Connection) -> list[str]:
        rows = conn.execute(
            text(
                "SELECT DISTINCT import_id FROM import_statements WHERE status = 'needs_review' "
                "AND reasons_json LIKE '%unknown_account%'"
            )
        )
        return [str(r[0]) for r in rows]

    def apply(self, conn: Connection, params: BaseModel, proposal_id: str) -> dict[str, Any]:
        assert isinstance(params, CreateAccount)  # noqa: S101
        try:
            a = catalog.add_account(
                conn,
                institution=params.institution,
                name=params.name,
                kind=params.kind,
                currency=params.currency,
                iban=params.iban,
                external_ref=params.external_ref,
                liquid=params.liquid,
                budget_account=params.budget_account,
            )
        except catalog.CatalogError as exc:
            raise _bad(str(exc)) from None
        return {"account_id": a.id, "iban": mask_iban(a.iban)}

    def after_commit(self, params: BaseModel, result: dict[str, Any]) -> None:
        """Les imports en attente sur ce compte sont relancés ; un compte Revolut (Enable
        Banking) s'ouvre d'abord au solde déduit de sa reprise complète, comme
        `fin revolut add-account`."""
        assert isinstance(params, CreateAccount)  # noqa: S101
        service = self.domain.importer
        if (params.external_ref or "").startswith("revolut:"):
            from hub.domains.finance import importer

            with self.domain.engine().connect() as conn:
                account = catalog.get_account(conn, str(result["account_id"]))
            if importer.open_revolut(service, account)[0]:
                return
        service.retry_needs_review(quiet=True)


GOAL_LABEL = {
    "current": "Courant",
    "safety": "Réserve de sécurité",
    "projects": "Projets",
    "long_term": "Long terme",
    "retirement": "Retraite",
}


class SetAccountGoal(_Params):
    account_id: str = Field(min_length=1, max_length=40)
    goal: Literal["current", "safety", "projects", "long_term", "retirement"]


class SetAccountGoalHandler:
    def _row(self, conn: Connection, account_id: str) -> Any:
        row = conn.execute(
            text("SELECT institution, name, goal FROM accounts WHERE id = :a"), {"a": account_id}
        ).first()
        if row is None:
            raise _bad("compte inconnu")
        return row

    def preview(self, conn: Connection, params: BaseModel) -> Preview:
        assert isinstance(params, SetAccountGoal)  # noqa: S101
        row = self._row(conn, params.account_id)
        before = f" (avant {GOAL_LABEL[row[2]]})" if row[2] else ""
        return Preview(
            summary=f"Objectif de {row[0]} « {row[1]} » : {GOAL_LABEL[params.goal]}{before}",
            details={"account_id": params.account_id, "goal": params.goal, "previous": row[2]},
            fingerprint=_fp("set_account_goal", params.account_id, row[2]),
        )

    def apply(self, conn: Connection, params: BaseModel, proposal_id: str) -> dict[str, Any]:
        assert isinstance(params, SetAccountGoal)  # noqa: S101
        previous = self._row(conn, params.account_id)[2]
        conn.execute(
            text("UPDATE accounts SET goal = :g WHERE id = :a"),
            {"g": params.goal, "a": params.account_id},
        )
        return {"account_id": params.account_id, "previous": previous}


AVAILABILITY_LABEL = {"immediate": "immédiate", "days": "sous quelques jours", "locked": "bloquée"}
CATEGORY_LABEL = {"cash": "Liquidités", "funds": "Actions et fonds", "crypto": "Crypto"}


class EditAccount(_Params):
    """Réglages d'un compte dans l'app ; un champ absent ne change pas, « auto » rend la
    déduction par type de compte."""

    account_id: str = Field(min_length=1, max_length=40)
    name: str | None = Field(default=None, min_length=1, max_length=60)
    goal: Literal["current", "safety", "projects", "long_term", "retirement"] | None = None
    availability: Literal["auto", "immediate", "days", "locked"] | None = None
    category: Literal["auto", "cash", "funds", "crypto"] | None = None
    hidden: bool | None = None


class EditAccountHandler:
    COLS = ("name", "goal", "availability", "category", "hidden")

    def _row(self, conn: Connection, account_id: str) -> dict[str, Any]:
        row = conn.execute(
            text(
                "SELECT institution, name, goal, availability, category, hidden "
                "FROM accounts WHERE id = :a"
            ),
            {"a": account_id},
        ).first()
        if row is None:
            raise _bad("compte inconnu")
        return {"institution": row[0], **dict(zip(self.COLS, row[1:], strict=True))}

    def _changes(self, row: dict[str, Any], p: EditAccount) -> dict[str, Any]:
        wanted: dict[str, Any] = {
            "name": p.name.strip() if p.name is not None else None,
            "goal": p.goal,
            "availability": p.availability,
            "category": p.category,
            "hidden": None if p.hidden is None else int(p.hidden),
        }
        out = {}
        for col, v in wanted.items():
            if v is None:
                continue
            value = None if v == "auto" else v
            if col == "name" and not value:
                raise _bad("nom vide")
            if value != row[col]:
                out[col] = value
        if not out:
            raise _bad("aucun changement")
        return out

    @staticmethod
    def _say(col: str, v: Any) -> str:
        if col == "name":
            return f"nom « {v} »"
        if col == "goal":
            return f"objectif {GOAL_LABEL[v].lower()}"
        if col == "availability":
            return f"disponibilité {AVAILABILITY_LABEL[v]}" if v else "disponibilité déduite"
        if col == "category":
            return f"catégorie {CATEGORY_LABEL[v].lower()}" if v else "catégorie déduite"
        return "masqué" if v else "affiché"

    def preview(self, conn: Connection, params: BaseModel) -> Preview:
        assert isinstance(params, EditAccount)  # noqa: S101
        row = self._row(conn, params.account_id)
        changes = self._changes(row, params)
        said = ", ".join(self._say(c, v) for c, v in changes.items())
        return Preview(
            summary=f"Compte {row['institution']} « {row['name']} » : {said}",
            details={"account_id": params.account_id, "changes": changes},
            fingerprint=_fp("edit_account", params.account_id, [row[c] for c in self.COLS]),
        )

    def apply(self, conn: Connection, params: BaseModel, proposal_id: str) -> dict[str, Any]:
        assert isinstance(params, EditAccount)  # noqa: S101
        row = self._row(conn, params.account_id)
        changes = self._changes(row, params)
        sets = ", ".join(f"{c} = :{c}" for c in changes)  # noms tirés de COLS, jamais du client
        conn.execute(
            text(f"UPDATE accounts SET {sets} WHERE id = :a"),
            {**changes, "a": params.account_id},
        )
        return {"account_id": params.account_id, "previous": {c: row[c] for c in changes}}


class CreateCategory(_Params):
    id: Slug
    name: str = Field(min_length=1, max_length=60)
    grp: Literal["fixed", "variable", "savings", "income", "transfer"]


class CreateCategoryHandler:
    def preview(self, conn: Connection, params: BaseModel) -> Preview:
        assert isinstance(params, CreateCategory)  # noqa: S101
        if conn.execute(text("SELECT 1 FROM categories WHERE id = :i"), {"i": params.id}).first():
            raise _bad(f"catégorie déjà connue : {params.id}")
        return Preview(
            summary=f"Nouvelle catégorie « {params.name} » ({params.grp})",
            details=params.model_dump(),
            fingerprint=_fp("create_category", "absent", params.id),
        )

    def apply(self, conn: Connection, params: BaseModel, proposal_id: str) -> dict[str, Any]:
        assert isinstance(params, CreateCategory)  # noqa: S101
        try:
            catalog.add_category(conn, id=params.id, name=params.name, grp=params.grp)
        except catalog.CatalogError as exc:
            raise _bad(str(exc)) from None
        return {"category_id": params.id}


# --- packs de règles (G6) -------------------------------------------------------------------


class InstallPack(_Params):
    name: Slug


def _pack(name: str) -> packs.Pack:
    found = packs.available().get(name)
    if found is None:
        raise _bad(f"pack inconnu : {name}")
    return found


class InstallPackHandler:
    """Installe ou met à jour un pack livré avec le hub ; ses règles catégorisent aussitôt les
    écritures sans catégorie. Une règle déjà présente sous une autre origine n'est pas doublée."""

    def preview(self, conn: Connection, params: BaseModel) -> Preview:
        assert isinstance(params, InstallPack)  # noqa: S101
        pack = _pack(params.name)
        report = packs.install(conn, pack, dry_run=True)
        before = packs.installed(conn).get(pack.name)
        verb = "Mettre à jour" if before is not None else "Installer"
        return Preview(
            summary=(
                f"{verb} le pack « {pack.label} » v{pack.version} : {report.added} règles, "
                f"{report.categories_added} catégories"
            ),
            details=report.public(),
            fingerprint=_fp("install_pack", rules.version(conn), pack.name, pack.version, before),
        )

    def apply(self, conn: Connection, params: BaseModel, proposal_id: str) -> dict[str, Any]:
        assert isinstance(params, InstallPack)  # noqa: S101
        return packs.install(conn, _pack(params.name)).public()


def build_kinds(domain: FinanceDomain) -> Mapping[str, ProposalKind]:
    return {
        "recategorize": ProposalKind(
            Recategorize,
            RecategorizeHandler(),
            reversible=True,
            inverse=_recategorize_inverse,
            ai_allowed=True,
        ),
        "create_rule": ProposalKind(CreateRule, CreateRuleHandler(), ai_allowed=True),
        "disable_rule": ProposalKind(DisableRule, DisableRuleHandler()),
        "set_budget": ProposalKind(
            SetBudget,
            SetBudgetHandler(domain),
            reversible=True,
            inverse=_budget_inverse,
            ai_allowed=True,
        ),
        "add_note": ProposalKind(AddNote, AddNoteHandler(), ai_allowed=True),
        "apply_import": ProposalKind(
            ApplyImport, ApplyImportHandler(domain), ttl=timedelta(days=7)
        ),
        "create_account": ProposalKind(CreateAccount, CreateAccountHandler(domain)),
        "create_category": ProposalKind(CreateCategory, CreateCategoryHandler()),
        "set_account_goal": ProposalKind(SetAccountGoal, SetAccountGoalHandler()),
        "edit_account": ProposalKind(EditAccount, EditAccountHandler()),
        "install_pack": ProposalKind(InstallPack, InstallPackHandler()),
        "categorize_rest": ProposalKind(CategorizeRest, CategorizeRestHandler()),
    }
