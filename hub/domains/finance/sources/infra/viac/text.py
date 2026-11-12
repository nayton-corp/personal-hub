"""Texte d'un PDF VIAC par `pdftotext -layout` (poppler), comme les scripts du Mac : la lecture
bornée du noyau (hub/kernel/pdf.py), ses refus en erreur VIAC."""

from __future__ import annotations

from hub.domains.finance.sources.infra.viac import ViacError
from hub.kernel import pdf

is_pdf = pdf.is_pdf


def pdftotext(data: bytes) -> str:
    """Texte « mise en page » du PDF, pages séparées par un saut de page (\\f)."""
    try:
        return pdf.pdftotext(data)
    except pdf.PdfError as exc:
        raise ViacError("viac.unreadable", str(exc)) from None
