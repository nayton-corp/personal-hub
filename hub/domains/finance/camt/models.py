"""Ce que produit le parseur camt.053 : des objets, jamais d'écriture en base."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

# anomalies qui empêchent l'application automatique : liste fermée (section 4, audit)
Anomaly = Literal[
    "internal_check_failed",  # OPBD + somme des écritures ≠ CLBD
    "ledger_check_failed",  # solde du registre à la date de CLBD ≠ CLBD
    "checkpoint_conflict",  # même date, autre montant qu'un solde déjà annoncé
    "near_duplicate",  # même compte, date et montant, clé différente
    "grouped_not_split",  # Ntry groupée dont les détails ne somment pas au montant
    "unknown_account",  # IBAN absent de accounts
    "unknown_currency",  # devise sans exposant connu
    "currency_mismatch",  # devise du relevé ≠ devise du compte
    "missing_balance",  # pas d'OPBD ou pas de CLBD
    "no_opening",  # compte sans solde d'ouverture
    "before_opening",  # relevé antérieur à l'ouverture du compte
]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Balance(_Frozen):
    on_date: str  # AAAA-MM-JJ
    amount_minor: int


class ParsedEntry(_Frozen):
    ntry_index: int  # rang de la Ntry dans le relevé
    detail_index: int | None  # rang du TxDtls dans la Ntry quand elle est découpée
    booking_date: str
    value_date: str | None
    amount_minor: int  # signé : DBIT négatif, inversé si RvslInd
    currency: str
    reversal: bool
    counterparty: str | None
    counterparty_iban: str | None
    label: str
    remittance: str
    bank_ref: str | None  # TxDtls/Refs/AcctSvcrRef, sinon Ntry/AcctSvcrRef
    detail_ref: str | None  # TxDtls/Refs/AcctSvcrRef seul (clé de dédoublonnage)
    bank_tx_code: str | None
    fx_json: str | None


class ParsedStatement(_Frozen):
    index: int
    iban: str | None
    currency: str | None
    opening: Balance | None
    closing: Balance | None
    entries: list[ParsedEntry]
    anomalies: list[Anomaly]
    ignored_pending: int  # écritures PDNG ou INFO, non importées


class ParsedFile(_Frozen):
    version: Literal["04", "08"]
    statements: list[ParsedStatement]
