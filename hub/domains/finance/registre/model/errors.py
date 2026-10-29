"""Refus d'un import ou d'une écriture : un code stable (`import.duplicate_file`…) et un
détail sans contenu de relevé."""

from __future__ import annotations


class ImportRefused(RuntimeError):
    """Refus d'un import ; `code` est un type d'erreur stable de l'API."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail
