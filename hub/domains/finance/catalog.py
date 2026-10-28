"""Comptes et catégories (ticket L1-12) : écriture directe tant que le Double Sas n'existe pas."""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError

from hub.core.clock import now_iso
from hub.core.ids import new_id
from hub.core.money import base_currency
from hub.core.text import compact_iban, is_iban

KINDS = ("cash", "securities", "pension", "crypto")
GROUPS = ("fixed", "variable", "savings", "income", "transfer")
_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{1,40}$")


class CatalogError(ValueError):
    pass


@dataclass(frozen=True)
class Account:
    id: str
    institution: str
    name: str
    kind: str
    currency: str
    iban: str | None
    external_ref: str | None
    liquid: bool
    budget_account: bool
    opened_on: str | None
    closed_on: str | None


@dataclass(frozen=True)
class Category:
    id: str
    name: str
    grp: str
    active: bool


_ACCOUNT_COLS = (
    "id, institution, name, kind, currency, iban, external_ref, liquid, budget_account, "
    "opened_on, closed_on"
)


def _account(r: tuple[object, ...]) -> Account:
    return Account(
        id=str(r[0]),
        institution=str(r[1]),
        name=str(r[2]),
        kind=str(r[3]),
        currency=str(r[4]),
        iban=r[5] if isinstance(r[5], str) else None,
        external_ref=r[6] if isinstance(r[6], str) else None,
        liquid=bool(r[7]),
        budget_account=bool(r[8]),
        opened_on=r[9] if isinstance(r[9], str) else None,
        closed_on=r[10] if isinstance(r[10], str) else None,
    )


def add_account(
    conn: Connection,
    *,
    institution: str,
    name: str,
    kind: str = "cash",
    currency: str | None = None,
    iban: str | None = None,
    external_ref: str | None = None,
    liquid: bool = False,
    budget_account: bool = False,
) -> Account:
    if kind not in KINDS:
        raise CatalogError(f"type de compte inconnu : {kind}")
    currency = currency or base_currency()
    if iban is not None:
        if not is_iban(iban):
            raise CatalogError("IBAN invalide")
        iban = compact_iban(iban)
    if iban is None and external_ref is None:
        raise CatalogError("un compte a un IBAN ou une référence externe")
    if (
        conn.execute(text("SELECT 1 FROM currencies WHERE code = :c"), {"c": currency}).first()
        is None
    ):
        raise CatalogError(f"devise inconnue : {currency}")
    account_id = new_id()
    try:
        conn.execute(
            text(
                "INSERT INTO accounts (id, institution, name, kind, currency, iban, external_ref, "
                "liquid, budget_account, created_at) VALUES (:id, :inst, :name, :kind, :ccy, "
                ":iban, :ext, :liquid, :budget, :at)"
            ),
            {
                "id": account_id,
                "inst": institution,
                "name": name,
                "kind": kind,
                "ccy": currency,
                "iban": iban,
                "ext": external_ref,
                "liquid": int(liquid),
                "budget": int(budget_account),
                "at": now_iso(),
            },
        )
    except IntegrityError as exc:
        raise CatalogError("compte déjà connu (IBAN ou référence externe)") from exc
    return get_account(conn, account_id)


def get_account(conn: Connection, account_id: str) -> Account:
    row = conn.execute(
        text(f"SELECT {_ACCOUNT_COLS} FROM accounts WHERE id = :id"),  # noqa: S608
        {"id": account_id},
    ).first()
    if row is None:
        raise CatalogError("compte inconnu")
    return _account(tuple(row))


def list_accounts(conn: Connection) -> list[Account]:
    rows = conn.execute(
        text(f"SELECT {_ACCOUNT_COLS} FROM accounts ORDER BY institution, name")  # noqa: S608
    )
    return [_account(tuple(r)) for r in rows]


def account_by_iban(conn: Connection, iban: str) -> Account | None:
    row = conn.execute(
        text(f"SELECT {_ACCOUNT_COLS} FROM accounts WHERE iban = :i"),  # noqa: S608
        {"i": compact_iban(iban)},
    ).first()
    return _account(tuple(row)) if row else None


def account_by_ref(conn: Connection, external_ref: str) -> Account | None:
    row = conn.execute(
        text(f"SELECT {_ACCOUNT_COLS} FROM accounts WHERE external_ref = :r"),  # noqa: S608
        {"r": external_ref},
    ).first()
    return _account(tuple(row)) if row else None


def own_ibans(conn: Connection) -> frozenset[str]:
    rows = conn.execute(text("SELECT iban FROM accounts WHERE iban IS NOT NULL"))
    return frozenset(str(r[0]) for r in rows)


def add_category(conn: Connection, *, id: str, name: str, grp: str) -> Category:
    if not _SLUG.match(id):
        raise CatalogError("identifiant de catégorie : minuscules, chiffres et tirets")
    if grp not in GROUPS:
        raise CatalogError(f"groupe inconnu : {grp}")
    try:
        conn.execute(
            text("INSERT INTO categories (id, name, grp) VALUES (:id, :name, :grp)"),
            {"id": id, "name": name, "grp": grp},
        )
    except IntegrityError as exc:
        raise CatalogError(f"catégorie déjà connue : {id}") from exc
    return Category(id=id, name=name, grp=grp, active=True)


def list_categories(conn: Connection) -> list[Category]:
    rows = conn.execute(text("SELECT id, name, grp, active FROM categories ORDER BY grp, name"))
    return [Category(id=r[0], name=r[1], grp=r[2], active=bool(r[3])) for r in rows]
