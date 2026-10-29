"""Documents VIAC (lot 4) : avis d'opération et rapport, lus depuis le texte du PDF.

Portage de `viac_parser.py` et `viac_rapport.py` du Mac : mêmes motifs de lecture, mais en
`Decimal`, avec une liste fermée de types, et un refus plutôt qu'une ligne « inconnu ».
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation

# nombre tel que VIAC l'imprime : 1'234.56, 1’234.56, -12.5
NUM = r"[-+]?\d[\d'’]*(?:\.\d+)?"
DATE = r"\d{2}\.\d{2}\.\d{4}"
PORTFOLIO = r"\d\.\d{3}\.\d{3}\.\d{3}\.\d{2}"


class ViacError(ValueError):
    """Document refusé ; `code` est un type d'erreur stable (`viac.unreadable`…)."""

    def __init__(self, code: str, reason: str) -> None:
        super().__init__(reason)
        self.code = code
        self.reason = reason


def num(value: str) -> Decimal:
    clean = value.replace("'", "").replace("’", "").replace("+", "").strip()
    try:
        out = Decimal(clean)
    except InvalidOperation:
        raise ViacError("viac.unrecognized", "nombre illisible") from None
    if not out.is_finite():
        raise ViacError("viac.unrecognized", "nombre illisible")
    return out


def iso(value: str) -> str:
    try:
        d, m, y = (int(x) for x in value.split("."))
        return date(y, m, d).isoformat()
    except ValueError:
        raise ViacError("viac.unrecognized", "date illisible") from None


def first(pattern: str, txt: str, flags: int = 0) -> str | None:
    m = re.search(pattern, txt, flags)
    return m.group(1) if m else None
