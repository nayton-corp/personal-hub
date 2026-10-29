"""Écriture d'un relevé IBKR au registre (lot 6) : les comptes de liquidités par devise, créés au
premier relevé, et les écritures de chacun, dédoublonnées par leur identifiant IBKR."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal, localcontext

from sqlalchemy import Connection, text

from hub.domains.finance.classement.app import rules
from hub.domains.finance.patrimoine.app import assets
from hub.domains.finance.patrimoine.model.instruments import Result
from hub.domains.finance.registre.app import catalog, ledger
from hub.domains.finance.sources.infra.ibkr_flex import (
    INSTITUTION,
    Trade,
    cash_ref,
)
from hub.kernel.clock import now_iso
from hub.kernel.money import DECIMAL_CONTEXT, Money


def _day_before(on: str) -> str:
    return (date.fromisoformat(on) - timedelta(days=1)).isoformat()


def _minor(amount: Decimal, currency: str) -> int:
    return Money.from_decimal(amount, currency).minor


def _ensure_cash(
    conn: Connection, titles: catalog.Account, account: str, ccy: str
) -> catalog.Account:
    found = catalog.account_by_ref(conn, cash_ref(account, ccy))
    if found is not None:
        return found
    return catalog.add_account(
        conn,
        institution=INSTITUTION,
        name=f"{titles.name} {ccy}",
        kind="securities",
        currency=ccy,
        external_ref=cash_ref(account, ccy),
    )


class Writer:
    """Écritures d'un relevé, catégorisées par les règles système (codes IBKR/…, SWISSBORG/…)."""

    def __init__(
        self,
        conn: Connection,
        import_id: str,
        account: str,
        result: Result,
        namespace: str = "ibkr",
    ) -> None:
        self.conn = conn
        self.namespace = namespace  # préfixe des clés de doublon : « ibkr », « swissborg »
        self.import_id = import_id
        self.account = account
        self.result = result
        self.ruleset = rules.load(conn)
        self.created = now_iso()
        self.touched: dict[str, int] = {}
        self.openings: dict[str, str | None] = {}

    def opened(self, account_id: str) -> str | None:
        if account_id not in self.openings:
            self.openings[account_id] = assets.opening_date(self.conn, account_id)
        return self.openings[account_id]

    def entry(
        self,
        target: catalog.Account,
        key: str,
        on: str,
        amount: int,
        code: str,
        label: str,
        *,
        counterparty: str | None = None,
        remittance: str = "",
        fx_json: str | None = None,
    ) -> None:
        dedup_key = ledger.dedup_hash(f"{self.namespace}|{self.account}|{key}")
        if self.conn.execute(
            text("SELECT 1 FROM entries WHERE dedup_key = :k"), {"k": dedup_key}
        ).first():
            self.result.duplicates += 1
            return
        opened = self.opened(target.id)
        if opened is None or on <= opened:
            self.result.review("before_opening" if opened else "no_opening")
            return
        e = ledger.NewEntry(
            account_id=target.id,
            booking_date=on,
            value_date=on,
            amount_minor=amount,
            currency=target.currency,
            counterparty=counterparty,
            label=label,
            remittance=remittance,
            bank_ref=key.split("|")[0][:60],
            bank_tx_code=code,
            fx_json=fx_json,
            dedup_key=dedup_key,
            import_id=self.import_id,
        )
        seq, _ = ledger.append_entry(self.conn, e, self.created)
        won = self.ruleset.winner(
            rules.Target(
                amount,
                ledger.search_text(counterparty, label, remittance),
                None,
                code,
                None,
                target.id,
            )
        )
        if won is not None:
            rules.categorize(self.conn, seq, won, proposal_id=None, created_at=self.created)
        self.result.new += 1
        self.touched[target.id] = self.touched.get(target.id, 0) + 1


def _base_amount(t: Trade, base: str) -> Decimal | None:
    """Contrevaleur d'un achat (positive) ou d'une vente (négative) en devise de base."""
    if t.currency == base:
        return -t.proceeds
    if t.fx_to_base is None:
        return None
    with localcontext(DECIMAL_CONTEXT):
        return -t.proceeds * t.fx_to_base
