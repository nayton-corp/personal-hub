"""Fichiers Revolut (lot 5) : JSON du collecteur Enable Banking et, en secours, l'export CSV de
l'app. Les deux deviennent des `ParsedStatement`, rapprochés et dédoublonnés comme un relevé
camt.053.

Un compte Revolut par devise, qui partagent parfois le même IBAN : le compte du registre se
reconnaît à sa clé `external_ref`, `revolut:<DEVISE>` pour le compte courant et
`revolut:<DEVISE>:<produit>` pour les autres (épargne, coffres).

Soldes : seuls les soldes comptabilisés (CLBD, ITBD) deviennent des points de contrôle ; un solde
disponible peut compter des paiements en attente. Le solde d'ouverture déduit (solde annoncé
moins les écritures) ne sert qu'à ouvrir le compte. Le CSV ne porte pas d'identifiant
d'écriture : un CSV qui recouvre des écritures venues d'Enable Banking produit des quasi-doublons,
signalés et mis en attente plutôt qu'importés deux fois.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from datetime import date, timedelta
from decimal import InvalidOperation
from typing import Any

from hub.core import canonical
from hub.core.money import CurrencyError, Money
from hub.core.text import normalize
from hub.domains.finance.camt.models import (
    Anomaly,
    Balance,
    ParsedEntry,
    ParsedFile,
    ParsedStatement,
)

EB_FORMAT = "hub.revolut.v1"
EB_SOURCE = "revolut_eb"
CSV_SOURCE = "revolut_csv"
SOURCES = frozenset({EB_SOURCE, CSV_SOURCE})
BOOKED = ("CLBD", "ITBD")  # soldes comptabilisés : points de contrôle
ANY_BALANCE = (*BOOKED, "XPCD", "CLAV", "ITAV", "OPBD", "PRCD", "OTHR")
CSV_HEADER = (
    "Type",
    "Product",
    "Started Date",
    "Completed Date",
    "Description",
    "Amount",
    "Fee",
    "Currency",
    "State",
    "Balance",
)
MAX_BYTES = 20 * 1024 * 1024


class RevolutError(ValueError):
    def __init__(self, reason: str, code: str = "import.invalid_schema") -> None:
        super().__init__(reason)
        self.code = code
        self.reason = reason


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", normalize(value)).strip("-")[:30] or "autre"


def account_ref(currency: str, product: str | None, current: bool, key: str = "") -> str:
    """`key` départage les comptes d'un même produit : chez Revolut UAB, le « produit » de chaque
    poche est le nom du titulaire, donc trois poches CHF auraient la même référence."""
    if current:
        return f"revolut:{currency}"
    suffix = f"-{hashlib.sha256(key.encode()).hexdigest()[:6]}" if key else ""
    return f"revolut:{currency}:{_slug(product or '')}{suffix}"


def _account_key(account: dict[str, Any]) -> str:
    """Identifiant stable d'un compte d'un consentement à l'autre (l'uid, lui, change)."""
    ident = account.get("account_id") or {}
    other = ident.get("other") or {} if isinstance(ident, dict) else {}
    for value in (
        account.get("identification_hash"),
        other.get("identification") if isinstance(other, dict) else None,
        ident.get("iban") if isinstance(ident, dict) else None,
    ):
        if value:
            return str(value)
    return ""


def is_eb(data: bytes) -> bool:
    if data.lstrip()[:1] != b"{":
        return False
    try:
        doc = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    return isinstance(doc, dict) and doc.get("format") == EB_FORMAT


def is_csv(data: bytes) -> bool:
    head = data.lstrip(b"\xef\xbb\xbf")[:300].decode("utf-8", "replace").splitlines()
    return bool(head) and tuple(c.strip() for c in head[0].split(",")) == CSV_HEADER


def _minor(amount: Any, currency: str) -> int:
    try:
        return Money.from_decimal(str(amount).replace("'", "").strip(), currency).minor
    except CurrencyError:
        raise
    except (ValueError, InvalidOperation):
        raise RevolutError("montant illisible") from None


def _iso(value: Any) -> str | None:
    if not value:
        return None
    text = str(value)[:10]
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        raise RevolutError("date illisible") from None


def _day_before(on: str) -> str:
    return (date.fromisoformat(on) - timedelta(days=1)).isoformat()


# --- Enable Banking -------------------------------------------------------------------------


def _eb_entry(tx: dict[str, Any], index: int, currency: str) -> ParsedEntry:
    amount = tx.get("transaction_amount") or {}
    ccy = str(amount.get("currency") or currency)
    minor = abs(_minor(amount.get("amount"), ccy))
    debit = tx.get("credit_debit_indicator") == "DBIT"
    party = (tx.get("creditor") if debit else tx.get("debtor")) or {}
    party_account = (tx.get("creditor_account") if debit else tx.get("debtor_account")) or {}
    lines = [str(x) for x in (tx.get("remittance_information") or []) if x]
    code = tx.get("bank_transaction_code") or {}
    tx_code = "/".join(str(code[k]) for k in ("code", "sub_code") if code.get(k)) or None
    ref = tx.get("entry_reference") or tx.get("transaction_id")
    booking = _iso(tx.get("booking_date") or tx.get("transaction_date") or tx.get("value_date"))
    if booking is None:
        raise RevolutError("écriture sans date")
    fx = tx.get("exchange_rate")
    return ParsedEntry(
        ntry_index=index,
        detail_index=None,
        booking_date=booking,
        value_date=_iso(tx.get("value_date")),
        amount_minor=-minor if debit else minor,
        currency=ccy,
        reversal=False,
        counterparty=(str(party.get("name")) if party.get("name") else None),
        counterparty_iban=(str(party_account["iban"]) if party_account.get("iban") else None),
        label=lines[0] if lines else str(code.get("description") or ""),
        remittance=" ".join(lines),
        bank_ref=str(ref) if ref else None,
        detail_ref=str(ref) if ref else None,
        bank_tx_code=tx_code,
        fx_json=canonical.dumps(fx) if fx else None,
    )


def _balance(
    balances: list[dict[str, Any]], kinds: tuple[str, ...], fallback: str
) -> Balance | None:
    for kind in kinds:
        for b in balances:
            if b.get("balance_type") == kind:
                amount = b.get("balance_amount") or {}
                ccy = str(amount.get("currency") or "")
                on = _iso(b.get("reference_date")) or fallback
                return Balance(on_date=on, amount_minor=_minor(amount.get("amount"), ccy))
    return None


def parse_eb(data: bytes) -> ParsedFile:
    if len(data) > MAX_BYTES:
        raise RevolutError("fichier trop volumineux")
    try:
        doc = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise RevolutError("JSON illisible") from None
    if not isinstance(doc, dict) or doc.get("format") != EB_FORMAT:
        raise RevolutError("pas un fichier Revolut du collecteur")
    account = doc.get("account") or {}
    currency = str(account.get("currency") or "")
    if not re.fullmatch(r"[A-Z]{3}", currency):
        raise RevolutError("compte sans devise")
    ref = account_ref(
        currency,
        str(
            account.get("product") or account.get("name") or account.get("cash_account_type") or ""
        ),
        account.get("cash_account_type", "CACC") == "CACC",
        _account_key(account),
    )
    date_to = _iso(doc.get("date_to")) or _iso(doc.get("fetched_at")) or "1970-01-01"
    anomalies: list[Anomaly] = []
    entries: list[ParsedEntry] = []
    pending = 0
    raw = [t for t in doc.get("transactions") or [] if isinstance(t, dict)]
    try:
        for i, tx in enumerate(raw):
            if tx.get("status", "BOOK") != "BOOK":
                pending += 1
                continue
            e = _eb_entry(tx, i, currency)
            if e.currency != currency:
                anomalies.append("currency_mismatch")
            entries.append(e)
        balances = [b for b in doc.get("balances") or [] if isinstance(b, dict)]
        closing = _balance(balances, BOOKED, date_to)
        announced = closing or _balance(balances, ANY_BALANCE, date_to)
    except CurrencyError:
        return _unknown_currency("revolut-eb1", ref, currency)
    entries.sort(key=lambda e: (e.booking_date, e.ntry_index))
    derived = None
    if announced is not None:
        upto = [e for e in entries if e.booking_date <= announced.on_date]
        first = min([e.booking_date for e in upto], default=announced.on_date)
        derived = Balance(
            on_date=_day_before(first),
            amount_minor=announced.amount_minor - sum(e.amount_minor for e in upto),
        )
    return ParsedFile(
        version="revolut-eb1",
        statements=[
            ParsedStatement(
                index=0,
                iban=None,
                currency=currency,
                opening=None,
                closing=closing,
                entries=entries,
                anomalies=sorted(set(anomalies)),
                ignored_pending=pending,
                account_ref=ref,
                derived_opening=derived,
            )
        ],
    )


def _unknown_currency(version: Any, ref: str, currency: str) -> ParsedFile:
    return ParsedFile(
        version=version,
        statements=[
            ParsedStatement(
                index=0,
                iban=None,
                currency=currency,
                opening=None,
                closing=None,
                entries=[],
                anomalies=["unknown_currency"],
                ignored_pending=0,
                account_ref=ref,
            )
        ],
    )


# --- CSV de l'app (secours) ---------------------------------------------------------------------


def parse_csv(data: bytes) -> ParsedFile:
    """Relevé CSV de l'app Revolut : un relevé par produit et devise, écritures COMPLETED."""
    if len(data) > MAX_BYTES:
        raise RevolutError("fichier trop volumineux")
    if not is_csv(data):
        raise RevolutError("pas un relevé CSV Revolut")
    text = data.decode("utf-8-sig", "replace")
    groups: dict[tuple[str, str], list[dict[str, str]]] = {}
    for row in csv.DictReader(io.StringIO(text)):
        key = ((row.get("Product") or "").strip(), (row.get("Currency") or "").strip())
        groups.setdefault(key, []).append(row)
    statements = []
    for index, ((product, currency), rows) in enumerate(sorted(groups.items())):
        ref = account_ref(currency, product, product.lower() in {"current", "courant"})
        try:
            statements.append(_csv_statement(index, ref, currency, rows))
        except CurrencyError:
            statements.append(_unknown_currency("revolut-csv1", ref, currency).statements[0])
            statements[-1] = statements[-1].model_copy(update={"index": index})
    if not statements:
        raise RevolutError("relevé vide")
    return ParsedFile(version="revolut-csv1", statements=statements)


def _csv_statement(
    index: int, ref: str, currency: str, rows: list[dict[str, str]]
) -> ParsedStatement:
    pending = 0
    done: list[tuple[str, int, dict[str, str]]] = []
    for i, row in enumerate(rows):
        state = (row.get("State") or "").strip().upper()
        if state == "PENDING":
            pending += 1
            continue
        if state != "COMPLETED":
            continue  # annulée, refusée : jamais comptabilisée
        completed = (row.get("Completed Date") or "").strip()
        if not completed:
            raise RevolutError("écriture sans date")
        done.append((completed, i, row))
    done.sort(key=lambda x: (x[0], x[1]))
    entries: list[ParsedEntry] = []
    anomalies: list[Anomaly] = []
    first_balance: int | None = None
    running: int | None = None
    for n, (completed, _i, row) in enumerate(done):
        net = _minor(row.get("Amount"), currency) - _minor(row.get("Fee") or "0", currency)
        kind = re.sub(r"[^A-Z_]", "", (row.get("Type") or "").upper().replace(" ", "_"))
        entries.append(
            ParsedEntry(
                ntry_index=n,
                detail_index=None,
                booking_date=_iso(completed) or "",
                value_date=_iso(row.get("Started Date")),
                amount_minor=net,
                currency=currency,
                reversal=False,
                counterparty=None,
                counterparty_iban=None,
                label=(row.get("Description") or "").strip(),
                remittance="",
                bank_ref=None,
                detail_ref=None,
                bank_tx_code=f"REVOLUT/{kind}" if kind else None,
                fx_json=None,
            )
        )
        balance = (row.get("Balance") or "").strip()
        if running is not None:
            running += net
        if balance:
            value = _minor(balance, currency)
            if running is None:
                first_balance, running = value - net, value
            elif value != running:
                # chaque ligne porte le solde après elle : un écart trahit une ligne manquante
                anomalies.append("internal_check_failed")
                running = value
    closing = derived = None
    if entries and first_balance is not None and running is not None:
        closing = Balance(on_date=entries[-1].booking_date, amount_minor=running)
        derived = Balance(on_date=_day_before(entries[0].booking_date), amount_minor=first_balance)
    return ParsedStatement(
        index=index,
        iban=None,
        currency=currency,
        opening=None,
        closing=closing,
        entries=entries,
        anomalies=sorted(set(anomalies)),
        ignored_pending=pending,
        account_ref=ref,
        derived_opening=derived,
    )


def parse(source: str, data: bytes) -> ParsedFile:
    if source == EB_SOURCE:
        return parse_eb(data)
    if source == CSV_SOURCE:
        return parse_csv(data)
    raise RevolutError(f"source inconnue : {source}")


def source_of(data: bytes) -> str | None:
    if is_eb(data):
        return EB_SOURCE
    if is_csv(data):
        return CSV_SOURCE
    return None
