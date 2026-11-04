"""Correction d'une écriture (audit M14) : le registre ne réécrit jamais une ligne. Une écriture
fausse (montant, date ou compte) est annulée par une écriture inverse, puis remplacée par une
nouvelle ; les deux sont `kind = 'correction'`, liées à l'originale par `corrects_seq`, et
reprennent sa catégorie. Les soldes comptent les trois lignes : l'annulation et la nouvelle
écriture font ensemble la différence. L'inverse corrige la nouvelle écriture avec les valeurs
d'origine : la chaîne reste lisible, rien n'est effacé."""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import Connection, text

from hub.core.domain import Preview
from hub.domains.finance.registre.app import ledger
from hub.domains.finance.registre.app.kinds import (
    EntryId,
    Params,
    RefreshAfter,
    bad,
    entry_brief,
    fp,
    shown_amount,
)
from hub.domains.finance.registre.model import dedup
from hub.kernel.clock import now_iso
from hub.kernel.ids import urn

EVENT = "entry.corrected"
_COLS = (
    "e.seq, e.id, e.kind, e.account_id, e.booking_date, e.value_date, e.amount_minor, "
    "e.currency, e.counterparty, e.counterparty_iban, e.label, e.remittance, e.bank_tx_code, "
    "e.dedup_key, vc.category_id, vc.categorization_seq"
)


class CorrectEntry(Params):
    entry_id: EntryId
    amount_minor: int | None = None  # signé, dans la devise de l'écriture ; absent : inchangé
    booking_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    account_id: str | None = Field(default=None, min_length=1, max_length=40)
    reason: str = Field(min_length=1, max_length=200)


def _row(conn: Connection, entry_id: str) -> Any:
    row = conn.execute(
        text(
            f"SELECT {_COLS} FROM entries e LEFT JOIN v_entry_category vc "  # noqa: S608
            "ON vc.entry_seq = e.seq WHERE e.id = :i"
        ),
        {"i": entry_id},
    ).first()
    if row is None:
        raise bad("écriture inconnue")
    return row


def _corrected(conn: Connection, seq: int) -> bool:
    return (
        conn.execute(
            text("SELECT 1 FROM entries WHERE corrects_seq = :s LIMIT 1"), {"s": seq}
        ).first()
        is not None
    )


def _key(proposal_id: str, part: str) -> str:
    return dedup.dedup_hash(f"correction|{proposal_id}|{part}")


def _account(conn: Connection, account_id: str, currency: str) -> str:
    row = conn.execute(
        text("SELECT name, currency, closed_on FROM accounts WHERE id = :a"), {"a": account_id}
    ).first()
    if row is None:
        raise bad("compte inconnu")
    if row[2]:
        raise bad("compte clos")
    if row[1] != currency:
        raise bad(f"le compte est en {row[1]}, l'écriture en {currency}")
    return str(row[0])


def _changes(conn: Connection, e: Any, params: CorrectEntry) -> dict[str, dict[str, Any]]:
    """Ce qui change, champ par champ ; rien à changer est un refus."""
    out: dict[str, dict[str, Any]] = {}
    if params.amount_minor is not None and params.amount_minor != int(e.amount_minor):
        if params.amount_minor == 0:
            raise bad("une écriture de 0 n'a pas de sens")
        out["amount"] = {
            "from": shown_amount(int(e.amount_minor), e.currency),
            "to": shown_amount(params.amount_minor, e.currency),
        }
    if params.booking_date is not None and params.booking_date != e.booking_date:
        date.fromisoformat(params.booking_date)
        out["booking_date"] = {"from": e.booking_date, "to": params.booking_date}
    if params.account_id is not None and params.account_id != e.account_id:
        name = _account(conn, params.account_id, e.currency)
        out["account"] = {"from": e.account_id, "to": params.account_id, "to_name": name}
    if not out:
        raise bad("rien à corriger : mêmes montant, date et compte")
    return out


def _check(conn: Connection, e: Any) -> None:
    if e.kind == "opening":
        raise bad("un solde d'ouverture ne se corrige pas")
    if e.kind == "correction" and _is_reversal(conn, e.seq):
        raise bad("une annulation ne se corrige pas : corriger l'écriture qui la remplace")
    if _corrected(conn, e.seq):
        raise bad("écriture déjà corrigée : corriger sa remplaçante")


def _is_reversal(conn: Connection, seq: int) -> bool:
    row = conn.execute(
        text("SELECT amount_minor, corrects_seq FROM entries WHERE seq = :s"), {"s": seq}
    ).first()
    if row is None or row[1] is None:
        return False
    original = conn.execute(
        text("SELECT amount_minor FROM entries WHERE seq = :s"), {"s": row[1]}
    ).scalar_one()
    return bool(int(row[0]) == -int(original))


def _said(changes: dict[str, dict[str, Any]]) -> str:
    parts = []
    if "amount" in changes:
        parts.append(f"{changes['amount']['from']} → {changes['amount']['to']}")
    if "booking_date" in changes:
        parts.append(f"du {changes['booking_date']['from']} au {changes['booking_date']['to']}")
    if "account" in changes:
        parts.append(f"vers {changes['account']['to_name']}")
    return ", ".join(parts)


class CorrectEntryHandler(RefreshAfter):
    def preview(self, conn: Connection, params: BaseModel) -> Preview:
        assert isinstance(params, CorrectEntry)  # noqa: S101
        e = _row(conn, params.entry_id)
        _check(conn, e)
        changes = _changes(conn, e, params)
        who = ledger.party(e.counterparty) or e.label or "écriture"
        return Preview(
            summary=f"Corriger {who} : {_said(changes)}",
            details={
                "entries": [entry_brief(e)],
                "changes": changes,
                "reason": params.reason,
                "effect": "une écriture d'annulation et une nouvelle écriture, liées à "
                "l'originale ; la catégorie suit",
            },
            fingerprint=fp("correct_entry", e.id, e.categorization_seq),
        )

    def apply(self, conn: Connection, params: BaseModel, proposal_id: str) -> dict[str, Any]:
        assert isinstance(params, CorrectEntry)  # noqa: S101
        e = _row(conn, params.entry_id)
        _check(conn, e)
        _changes(conn, e, params)
        at = now_iso()
        common = {
            "currency": e.currency,
            "kind": "correction",
            "value_date": e.value_date,
            "counterparty": e.counterparty,
            "counterparty_iban": e.counterparty_iban,
            "remittance": e.remittance,
            "bank_tx_code": e.bank_tx_code,
            "corrects_seq": int(e.seq),
            "proposal_id": proposal_id,
        }
        reverse = ledger.NewEntry(
            account_id=e.account_id,
            booking_date=e.booking_date,
            amount_minor=-int(e.amount_minor),
            dedup_key=_key(proposal_id, "reverse"),
            label=f"Annulation : {e.label}"[:200] if e.label else "Annulation",
            **common,
        )
        new = ledger.NewEntry(
            account_id=params.account_id or e.account_id,
            booking_date=params.booking_date or e.booking_date,
            amount_minor=params.amount_minor if params.amount_minor is not None else e.amount_minor,
            dedup_key=_key(proposal_id, "new"),
            label=e.label,
            **common,
        )
        r_seq, r_id = ledger.append_entry(conn, reverse, at)
        n_seq, n_id = ledger.append_entry(conn, new, at)
        if e.category_id:
            for seq in (r_seq, n_seq):
                ledger.append(
                    conn,
                    "categorizations",
                    {
                        "entry_seq": seq,
                        "category_id": e.category_id,
                        "source": "user",
                        "rule_id": None,
                        "proposal_id": proposal_id,
                        "created_at": at,
                    },
                )
        ledger.append_event(
            conn,
            EVENT,
            urn("finance", "entry", str(e.seq)),
            {"reversal": r_id, "replacement": n_id, "reason": params.reason},
        )
        return {
            "entry_id": e.id,
            "reversal_id": r_id,
            "replacement_id": n_id,
            "previous": {
                "amount_minor": int(e.amount_minor),
                "booking_date": e.booking_date,
                "account_id": e.account_id,
            },
        }


def correct_inverse(params: dict[str, Any], result: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Annuler une correction : corriger la remplaçante avec les valeurs d'origine."""
    before = result["previous"]
    return "correct_entry", {
        "entry_id": str(result["replacement_id"]),
        "amount_minor": int(before["amount_minor"]),
        "booking_date": str(before["booking_date"]),
        "account_id": str(before["account_id"]),
        "reason": f"Annulation de la correction : {params.get('reason', '')}"[:200],
    }
