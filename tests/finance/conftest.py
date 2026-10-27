from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from pathlib import Path

import pyrage
import pytest
from sqlalchemy import text

from hub.core.db import begin_immediate
from hub.core.settings import Paths, Secrets, Server, Settings
from hub.domains.finance import catalog, importer
from hub.domains.finance.domain import FinanceDomain
from tests.factories.camt import IBAN, Stmt, Tx

D = date(2026, 10, 1)


def finance_settings(tmp_path: Path) -> Settings:
    key = tmp_path / "age.key"
    if not key.exists():
        key.parent.mkdir(parents=True, exist_ok=True)
        key.write_text(f"# clé de test\n{pyrage.x25519.Identity.generate()}\n")
    return Settings(
        paths=Paths(
            data=tmp_path / "data",
            inbox=tmp_path / "inbox",
            archive=tmp_path / "archive",
            backup=tmp_path / "backup",
        ),
        server=Server(public_origin="https://hub.example.ts.net"),
        secrets=Secrets(file=tmp_path / "absent.enc.yaml", age_key_file=key),
    )


@pytest.fixture
def fsettings(tmp_path: Path) -> Settings:
    return finance_settings(tmp_path)


@pytest.fixture
def finance(fsettings: Settings) -> Iterator[FinanceDomain]:
    domain = FinanceDomain(fsettings)
    domain.migrate()
    yield domain
    domain.engine().dispose()


def add_account(domain: FinanceDomain, iban: str = IBAN, **kw: object) -> catalog.Account:
    with begin_immediate(domain.engine()) as conn:
        return catalog.add_account(conn, institution="BCF", name="Compte privé", iban=iban, **kw)  # type: ignore[arg-type]


def open_account(domain: FinanceDomain, account: catalog.Account, on: str, minor: int) -> None:
    with begin_immediate(domain.engine()) as conn:
        importer.open_account(conn, account.id, on, minor, account.currency)


def ready_account(domain: FinanceDomain, opening_minor: int = 100_000) -> catalog.Account:
    """Compte BCF ouvert la veille du 1er octobre 2026."""
    a = add_account(domain)
    open_account(domain, a, "2026-09-30", opening_minor)
    return a


def simple_stmt(opening: str = "1000.00", **kw: object) -> Stmt:
    return Stmt(
        opening=Decimal(opening),
        opening_date=D,
        entries=[
            Tx("20.00", True, D, label="TWINT", counterparty="Jean Exemple"),
            Tx("20.00", True, D, label="TWINT", counterparty="Jean Exemple"),
            Tx("2500.00", False, date(2026, 10, 2), counterparty="Employeur Fictif SA"),
        ],
        **kw,  # type: ignore[arg-type]
    )


def rows(domain: FinanceDomain, sql: str, **params: object) -> list[tuple[object, ...]]:
    with domain.engine().connect() as conn:
        return [tuple(r) for r in conn.execute(text(sql), params)]


def ledger_state(domain: FinanceDomain) -> list[tuple[object, ...]]:
    """Contenu métier du registre, sans horodatages ni identifiants d'import."""
    return rows(
        domain,
        "SELECT id, account_id, kind, booking_date, amount_minor, counterparty, label, dedup_key "
        "FROM entries ORDER BY booking_date, dedup_key",
    )


def without_seed_rules(domain: FinanceDomain) -> None:
    """Les tests de lecture décident eux-mêmes des catégories : règles de départ coupées."""
    with begin_immediate(domain.engine()) as conn:
        conn.execute(text("UPDATE rules SET active = 0 WHERE id LIKE 'seed-%'"))
