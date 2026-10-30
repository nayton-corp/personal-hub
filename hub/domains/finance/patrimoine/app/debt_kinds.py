"""Propositions sur les dettes : créer ou modifier une dette, relever son solde."""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Any, Literal, Protocol

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import Connection, text

from hub.core.domain import Preview
from hub.domains.finance.patrimoine.app import debts
from hub.domains.finance.registre.app import catalog, ledger
from hub.domains.finance.registre.app.kinds import (
    EntryId,
    Params,
    bad,
    category_row,
    fp,
    shown_amount,
)
from hub.kernel.clock import now_iso
from hub.kernel.ids import new_id, urn
from hub.kernel.money import base_currency


class Host(Protocol):
    """Ce que les handlers attendent du domaine (`FinanceDomain` le remplit)."""

    def refresh_snapshots(self) -> object: ...


DateStr = Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$")]
# « vide » efface un champ facultatif : "" pour un texte, 0 pour un montant ou un taux
Clearable = Annotated[str, Field(pattern=r"^(\d{4}-\d{2}-\d{2})?$")]
RatePct = Annotated[str, Field(pattern=r"^\d{1,2}(\.\d{1,4})?$")]
Amount = Annotated[int, Field(ge=0, le=100_000_000_000)]


class SaveDebt(Params):
    """Crée une dette (sans `debt_id` : nom, prêteur, type et départ requis) ou en change les
    champs donnés ; un champ absent ne change pas. Le départ est un solde à une date, ou
    l'écriture du versement reçu du prêteur (`opening_entry_id`) : sa date et son montant. Le
    montant emprunté prend celui du départ s'il n'est pas donné. La mensualité et l'échéance
    sont facultatives : sans mensualité, la projection suit les derniers paiements."""

    debt_id: str | None = Field(default=None, min_length=1, max_length=40)
    name: str | None = Field(default=None, min_length=1, max_length=60)
    lender: str | None = Field(default=None, min_length=1, max_length=60)
    kind: Literal["loan", "mortgage", "leasing", "student", "credit", "other"] | None = None
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")  # à la création
    original_minor: Amount | None = None  # montant emprunté ; 0 efface
    rate_pct: RatePct | None = None  # taux annuel en % ; "0" : sans intérêt
    payment_minor: Amount | None = None  # mensualité ; 0 efface
    ends_on: Clearable | None = None
    category_id: Annotated[str, Field(pattern=r"^([a-z0-9][a-z0-9-]{1,40})?$")] | None = None
    account_id: Annotated[str, Field(max_length=40)] | None = None  # "" : tout compte
    closed_on: Clearable | None = None  # "" : rouverte
    # départ, à la création seulement : un solde à une date, ou l'écriture du versement reçu
    balance_minor: Amount | None = None
    balance_on: DateStr | None = None
    opening_entry_id: EntryId | None = None

    @model_validator(mode="after")
    def _create(self) -> SaveDebt:
        by_hand = self.balance_minor is not None or self.balance_on is not None
        if self.debt_id is None:
            missing = [f for f in ("name", "lender", "kind") if getattr(self, f) is None]
            if self.opening_entry_id is None and (
                self.balance_minor is None or self.balance_on is None
            ):
                missing.append("balance_minor et balance_on, ou opening_entry_id")
            if missing:
                raise ValueError(f"champs requis pour une nouvelle dette : {', '.join(missing)}")
            if by_hand and self.opening_entry_id is not None:
                raise ValueError("départ : un solde ou une écriture, pas les deux")
        elif self.currency is not None or by_hand or self.opening_entry_id is not None:
            raise ValueError("devise et départ se donnent à la création")
        return self


class SaveDebtHandler:
    COLS = (
        "name",
        "lender",
        "kind",
        "currency",
        "original_minor",
        "rate",
        "payment_minor",
        "ends_on",
        "category_id",
        "account_id",
        "closed_on",
    )

    def __init__(self, domain: Host) -> None:
        self.domain = domain

    def _row(self, conn: Connection, debt_id: str) -> dict[str, Any]:
        row = conn.execute(
            text(f"SELECT {', '.join(self.COLS)} FROM debts WHERE id = :i"),
            {"i": debt_id},
        ).first()
        if row is None:
            raise bad("dette inconnue")
        return dict(zip(self.COLS, row, strict=True))

    def _wanted(self, conn: Connection, p: SaveDebt) -> dict[str, Any]:
        """Colonnes demandées, une valeur vide devenue NULL ; vérifie catégorie et compte."""
        out: dict[str, Any] = {}
        for col in ("name", "lender"):
            v = getattr(p, col)
            if v is not None:
                if not v.strip():
                    raise bad(f"{col} vide")
                out[col] = v.strip()
        if p.kind is not None:
            out["kind"] = p.kind
        if p.currency is not None:
            if (
                conn.execute(
                    text("SELECT 1 FROM currencies WHERE code = :c"), {"c": p.currency}
                ).first()
                is None
            ):
                raise bad(f"devise inconnue : {p.currency}")
            out["currency"] = p.currency
        for col in ("original_minor", "payment_minor"):
            v = getattr(p, col)
            if v is not None:
                out[col] = v or None
        if p.rate_pct is not None:
            rate = Decimal(p.rate_pct) / 100
            out["rate"] = str(rate.normalize()) if rate else None
        for col in ("ends_on", "closed_on"):
            v = getattr(p, col)
            if v is not None:
                out[col] = v or None
        if p.category_id is not None:
            if p.category_id:
                category_row(conn, p.category_id)
            out["category_id"] = p.category_id or None
        if p.account_id is not None:
            if p.account_id and catalog.get_account(conn, p.account_id) is None:
                raise bad("compte inconnu")
            out["account_id"] = p.account_id or None
        return out

    @staticmethod
    def opening(conn: Connection, p: SaveDebt, currency: str) -> tuple[str, int, str | None]:
        """(date, montant, écriture) du départ d'une nouvelle dette."""
        if p.opening_entry_id is None:
            return str(p.balance_on), int(p.balance_minor or 0), None
        row = conn.execute(
            text("SELECT booking_date, amount_minor, currency FROM entries WHERE id = :i"),
            {"i": p.opening_entry_id},
        ).first()
        if row is None:
            raise bad("écriture inconnue")
        if row[2] != currency:
            raise bad("l'écriture n'est pas dans la devise de la dette")
        return str(row[0]), abs(int(row[1])), p.opening_entry_id

    def _changes(
        self, conn: Connection, p: SaveDebt
    ) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        wanted = self._wanted(conn, p)
        if p.debt_id is None:
            wanted["currency"] = wanted.get("currency") or base_currency()
            on, amount, _entry = self.opening(conn, p, wanted["currency"])
            if amount <= 0:
                raise bad("solde de départ nul")
            wanted["original_minor"] = wanted.get("original_minor") or amount
            wanted["_opening"] = (on, amount)
            return None, wanted
        row = self._row(conn, p.debt_id)
        changes = {c: v for c, v in wanted.items() if v != row[c]}
        if not changes:
            raise bad("aucun changement")
        return row, changes

    def preview(self, conn: Connection, params: BaseModel) -> Preview:
        assert isinstance(params, SaveDebt)  # noqa: S101
        row, changes = self._changes(conn, params)
        if row is None:
            on, amount = changes.pop("_opening")
            summary = (
                f"Nouvelle dette « {changes['name']} » ({debts.KIND_LABEL[changes['kind']]}, "
                f"{changes['lender']}) : {shown_amount(amount, changes['currency'])} au {on}"
            )
            digest = fp("save_debt", "absent", changes["name"])
        else:
            summary = f"Dette « {row['name']} » : {', '.join(sorted(changes))} modifiés"
            if changes.get("closed_on"):
                summary = f"Dette « {row['name']} » close au {changes['closed_on']}"
            digest = fp("save_debt", params.debt_id, [row[c] for c in self.COLS])
        return Preview(
            summary=summary,
            details={"debt_id": params.debt_id, "changes": changes},
            fingerprint=digest,
        )

    def apply(self, conn: Connection, params: BaseModel, proposal_id: str) -> dict[str, Any]:
        assert isinstance(params, SaveDebt)  # noqa: S101
        row, changes = self._changes(conn, params)
        at = now_iso()
        if row is None:
            debt_id = new_id()
            changes.pop("_opening")
            on, amount, entry_id = self.opening(conn, params, changes["currency"])
            values = {c: changes.get(c) for c in self.COLS}
            conn.execute(
                text(
                    f"INSERT INTO debts (id, {', '.join(self.COLS)}, created_at, updated_at) "
                    f"VALUES (:id, {', '.join(':' + c for c in self.COLS)}, :at, :at)"
                ),
                {**values, "id": debt_id, "at": at},
            )
            debts.record_balance(conn, debt_id, on, amount, "opening", proposal_id, entry_id)
            previous: dict[str, Any] = {}
        else:
            debt_id = str(params.debt_id)
            sets = ", ".join(f"{c} = :{c}" for c in changes)  # noms tirés de COLS
            conn.execute(
                text(f"UPDATE debts SET {sets}, updated_at = :at WHERE id = :i"),
                {**changes, "at": at, "i": debt_id},
            )
            previous = {c: row[c] for c in changes}
        ledger.append_event(conn, "debt.changed", urn("finance", "debt", debt_id))
        return {"debt_id": debt_id, "previous": previous}

    def after_commit(self, params: BaseModel, result: dict[str, Any]) -> None:
        self.domain.refresh_snapshots()


class RecordDebtBalance(Params):
    """Solde constaté d'une dette (relevé du prêteur) : le calcul repart de là."""

    debt_id: str = Field(min_length=1, max_length=40)
    on_date: DateStr
    amount_minor: Amount


class RecordDebtBalanceHandler:
    def __init__(self, domain: Host) -> None:
        self.domain = domain

    def _debt(self, conn: Connection, debt_id: str) -> Any:
        row = conn.execute(
            text("SELECT name, currency FROM debts WHERE id = :i"), {"i": debt_id}
        ).first()
        if row is None:
            raise bad("dette inconnue")
        return row

    def _before(self, conn: Connection, p: RecordDebtBalance) -> int | None:
        return conn.execute(
            text("SELECT amount_minor FROM debt_balances WHERE debt_id = :i AND on_date = :d"),
            {"i": p.debt_id, "d": p.on_date},
        ).scalar_one_or_none()

    def preview(self, conn: Connection, params: BaseModel) -> Preview:
        assert isinstance(params, RecordDebtBalance)  # noqa: S101
        name, ccy = self._debt(conn, params.debt_id)
        before = self._before(conn, params)
        return Preview(
            summary=(
                f"Dette « {name} » : solde de {shown_amount(params.amount_minor, ccy)} "
                f"au {params.on_date}"
            ),
            details={**params.model_dump(), "previous": before},
            fingerprint=fp("record_debt_balance", params.debt_id, params.on_date, before),
        )

    def apply(self, conn: Connection, params: BaseModel, proposal_id: str) -> dict[str, Any]:
        assert isinstance(params, RecordDebtBalance)  # noqa: S101
        self._debt(conn, params.debt_id)
        before = self._before(conn, params)
        debts.record_balance(
            conn, params.debt_id, params.on_date, params.amount_minor, "statement", proposal_id
        )
        ledger.append_event(conn, "debt.changed", urn("finance", "debt", params.debt_id))
        return {"debt_id": params.debt_id, "previous": before}

    def after_commit(self, params: BaseModel, result: dict[str, Any]) -> None:
        self.domain.refresh_snapshots()
