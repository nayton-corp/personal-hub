"""Clé de dédoublonnage (ticket L1-05, section 4 et ajouts de l'audit).

Avec une référence de détail (TxDtls/Refs/AcctSvcrRef), la base est
iban | date | montant | devise | référence | index dans la Ntry, sans le libellé, qui change
parfois entre deux exports ou entre .04 et .08. Sinon : référence de la Ntry, contrepartie et
libellé normalisés. Un rang d'occurrence distingue deux écritures identiques le même jour ; deux
exports qui se chevauchent contiennent les mêmes journées complètes, donc les mêmes rangs.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Sequence

from hub.domains.finance.registre.model.statements import ParsedEntry
from hub.kernel.text import normalize

DEDUP_VERSION = "v1"


def dedup_hash(base: str) -> str:
    return hashlib.sha256(f"{DEDUP_VERSION}|{base}".encode()).hexdigest()


def base(iban: str, e: ParsedEntry) -> str:
    head = [iban, e.booking_date, str(e.amount_minor), e.currency]
    if e.detail_ref:
        tail = [e.detail_ref, str(e.detail_index or 0)]
    else:
        tail = [
            e.bank_ref or "",
            normalize(e.counterparty or "")[:40],
            normalize(e.label)[:60],
        ]
    return "|".join(head + tail)


def keys(iban: str, entries: Sequence[ParsedEntry]) -> list[str]:
    """Une clé par écriture, dans l'ordre du fichier."""
    seen: Counter[str] = Counter()
    out = []
    for e in entries:
        b = base(iban, e)
        out.append(dedup_hash(f"{b}|{seen[b]}"))
        seen[b] += 1
    return out


def opening_key(account_ref: str) -> str:
    return dedup_hash(f"opening|{account_ref}")
