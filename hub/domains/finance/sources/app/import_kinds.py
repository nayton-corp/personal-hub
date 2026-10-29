"""Propositions des sources (ticket L3-02) : appliquer un import qui attend une revue, créer le
compte d'un relevé."""

from __future__ import annotations

from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field
from sqlalchemy import Connection, Engine, text

from hub.core.domain import Preview
from hub.core.errors import Problem
from hub.domains.finance.registre.app import catalog
from hub.domains.finance.registre.app.kinds import (
    Params,
    bad,
    fp,
    totals_by_currency,
)
from hub.domains.finance.registre.model import errors
from hub.domains.finance.sources.app import importer, revolut_accounts
from hub.kernel.money import base_currency
from hub.kernel.text import mask_iban


class Host(Protocol):
    """Ce que les handlers attendent du domaine (`FinanceDomain` le remplit)."""

    importer: importer.ImportService

    def engine(self) -> Engine: ...

    def refresh_snapshots(self) -> object: ...


class ApplyImport(Params):
    import_id: str = Field(min_length=10, max_length=40)


class ApplyImportHandler:
    def __init__(self, domain: Host) -> None:
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
        except errors.ImportRefused as exc:
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
                "totals": totals_by_currency(items),
            },
            fingerprint=fp("apply_import", status, keys),
        )

    def apply(self, conn: Connection, params: BaseModel, proposal_id: str) -> dict[str, Any]:
        assert isinstance(params, ApplyImport)  # noqa: S101
        try:
            outcomes = self.domain.importer.force(conn, params.import_id, proposal_id)
        except errors.ImportRefused as exc:
            raise Problem(exc.code, exc.detail) from None
        return {
            "import_id": params.import_id,
            "statements": len(outcomes),
            "new": sum(o.new for o in outcomes),
        }

    def after_commit(self, params: BaseModel, result: dict[str, Any]) -> None:
        self.domain.refresh_snapshots()


class CreateAccount(Params):
    institution: str = Field(min_length=2, max_length=40)
    name: str = Field(min_length=1, max_length=80)
    kind: Literal["cash", "securities", "pension", "crypto"] = "cash"
    currency: str = Field(default_factory=base_currency, pattern=r"^[A-Z]{3}$")
    iban: str | None = Field(default=None, max_length=40)
    external_ref: str | None = Field(default=None, max_length=80)
    liquid: bool = False
    budget_account: bool = False


class CreateAccountHandler:
    def __init__(self, domain: Host) -> None:
        self.domain = domain

    def preview(self, conn: Connection, params: BaseModel) -> Preview:
        assert isinstance(params, CreateAccount)  # noqa: S101
        if params.iban is None and params.external_ref is None:
            raise bad("un compte a un IBAN ou une référence externe")
        if params.iban is not None and catalog.account_by_iban(conn, params.iban):
            raise bad("compte déjà connu")
        if (
            params.external_ref is not None
            and conn.execute(
                text("SELECT 1 FROM accounts WHERE external_ref = :r"), {"r": params.external_ref}
            ).first()
        ):
            raise bad("compte déjà connu")
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
            fingerprint=fp("create_account", "absent", params.iban, params.external_ref),
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
            raise bad(str(exc)) from None
        return {"account_id": a.id, "iban": mask_iban(a.iban)}

    def after_commit(self, params: BaseModel, result: dict[str, Any]) -> None:
        """Les imports en attente sur ce compte sont relancés ; un compte Revolut (Enable
        Banking) s'ouvre d'abord au solde déduit de sa reprise complète, comme
        `fin revolut add-account`."""
        assert isinstance(params, CreateAccount)  # noqa: S101
        service = self.domain.importer
        if (params.external_ref or "").startswith("revolut:"):
            with self.domain.engine().connect() as conn:
                account = catalog.get_account(conn, str(result["account_id"]))
            if revolut_accounts.open_revolut(service, account)[0]:
                return
        service.retry_needs_review(quiet=True)
