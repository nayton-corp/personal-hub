"""Normalisation du texte pour la recherche et les règles."""

import re
import unicodedata

_SPACES = re.compile(r"\s+")


def normalize(text: str | None) -> str:
    """NFKD sans accents, minuscules, espaces réduits."""
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return _SPACES.sub(" ", stripped.casefold()).strip()


_IBAN = re.compile(r"^[A-Z]{2}[0-9]{2}[A-Z0-9]{8,30}$")


def compact_iban(iban: str) -> str:
    return iban.replace(" ", "").upper()


def mask_iban(iban: str | None) -> str | None:
    """Seule fonction de masquage : 'CH9300762011623852957' -> 'CH93…957'."""
    if iban is None:
        return None
    value = compact_iban(iban)
    if len(value) < 8:
        return "…"
    return f"{value[:4]}…{value[-3:]}"


def is_iban(value: str) -> bool:
    return bool(_IBAN.match(compact_iban(value)))
