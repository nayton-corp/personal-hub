"""Avis d'opération VIAC (ticket L4-03), portés de `viac_parser.py`.

Une opération par document : achat ou vente de parts, dividende, intérêts, commission,
versement, retrait, échange de fonds (« Transaction de fonds » : VIAC fusionne un fonds dans un
autre, les parts de l'ancien sortent et celles du nouveau entrent, sans liquidités). Les motifs
de lecture sont ceux du script du Mac ; ce qui ne se lit pas entièrement est refusé
(`viac.unrecognized`) au lieu de devenir une ligne « inconnu ». Les attestations fiscales et les
relevés récapitulatifs sont reconnus et n'écrivent rien : une attestation cite des versements,
elle ne doit pas en devenir un. Un décompte de commission à 0 CHF (mois sans frais) est reconnu
de la même façon : il n'y a rien à comptabiliser.
"""

from __future__ import annotations

import re
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from typing import Literal

from hub.domains.finance.sources.infra.viac import DATE, NUM, PORTFOLIO, ViacError, first, iso, num
from hub.domains.finance.sources.model.viac import Ignored, Notice, NoticeKind
from hub.kernel.money import DECIMAL_CONTEXT

Document = Literal["report", "notice", "attestation", "statement", "nil_fee"]
HEAD_LINES = 15
FEE_BOOKED = rf"Montant débité:\s+Valuta\s+({DATE})\s+CHF\s+({NUM})"
QTY_PLACES = 8  # parts recalculées quand l'avis les arrondit à zéro


def _head(txt: str) -> str:
    lines = [x for x in txt.splitlines() if x.strip()]
    return "\n".join(lines[:HEAD_LINES])


def classify(txt: str) -> Document:
    if re.search(rf"Rapport au {DATE}", txt) and "Récapitulation" in txt:
        return "report"
    head = _head(txt)
    if re.search(r"\bAttestation\b", head, re.I):
        return "attestation"
    if re.search(r"^\s*Relevé\b", head, re.M):
        return "statement"
    if re.search(r"^\s*Commission\s*$", txt, re.M):
        m = re.search(FEE_BOOKED, txt)
        if m and num(m.group(2)) == 0:
            return "nil_fee"
    return "notice"


def ignored(txt: str) -> Ignored | None:
    kind = classify(txt)
    if kind == "attestation":
        return Ignored(document="attestation")
    if kind == "statement":
        return Ignored(document="statement")
    if kind == "nil_fee":
        return Ignored(document="nil_fee")
    return None


def _portfolio(txt: str) -> str:
    raw = first(r"Portefeuille\s+([\d.]{8,})", txt)
    value = (raw or "").rstrip(".")
    if not re.fullmatch(PORTFOLIO, value):
        raise ViacError("viac.unrecognized", "numéro de portefeuille absent")
    return value


def _booked(pattern: str, txt: str) -> tuple[str, str]:
    m = re.search(pattern, txt)
    if m is None:
        raise ViacError("viac.unrecognized", "montant comptabilisé absent")
    return iso(m.group(1)), m.group(2)


def _fund(txt: str) -> tuple[str | None, str | None, str | None]:
    """(quantité, nom du fonds, ISIN) : « 12.345 parts CSIF … » puis « ISIN: CH… »."""
    m = re.search(rf"({NUM})\s+parts?\s+(.+?)\s*\n", txt)
    isin = first(r"ISIN:\s+([A-Z]{2}[A-Z0-9]{10})\b", txt)
    if m is None:
        return None, None, isin
    return m.group(1), re.sub(r"\s{2,}", " ", m.group(2)).strip(), isin


ISIN = r"[A-Z]{2}[A-Z0-9]{10}"


def _moved(label: str, txt: str) -> tuple[Decimal, str, str]:
    """(parts, fonds, ISIN) d'une ligne « Nous retirons / ajoutons à votre dépôt: … »."""
    m = re.search(rf"{label}:\s*({NUM})\s+(.+?)\s*/?\s*ISIN:\s*({ISIN})\b", txt, re.S)
    if m is None:
        raise ViacError("viac.unrecognized", "échange de fonds sans parts ou ISIN")
    quantity = abs(num(m.group(1)))
    if quantity == 0:
        raise ViacError("viac.unrecognized", "échange de fonds sans parts")
    return quantity, re.sub(r"\s+", " ", m.group(2)).strip(), m.group(3)


def _switch(txt: str, portfolio: str) -> Notice:
    out_qty, out_fund, out_isin = _moved("Nous retirons de votre dépôt", txt)
    in_qty, in_fund, in_isin = _moved("Nous ajoutons à votre dépôt", txt)
    if out_isin == in_isin:
        raise ViacError("viac.unrecognized", "échange de fonds vers le même ISIN")
    # la date de l'avis (après l'échange) ; à défaut, celle de l'état du dépôt avant l'échange
    on = first(rf"B[âa]le,\s+({DATE})", txt) or first(
        rf"(?:Etat|État) de votre dépôt au\s+({DATE})", txt
    )
    if on is None:
        raise ViacError("viac.unrecognized", "date de l'échange de fonds absente")
    return Notice(
        kind="switch",
        portfolio=portfolio,
        value_date=iso(on),
        amount=Decimal(0),
        isin=out_isin,
        fund=out_fund,
        quantity=out_qty,
        new_isin=in_isin,
        new_fund=in_fund,
        new_quantity=in_qty,
        detail=f"{out_fund} → {in_fund}"[:80],
    )


def parse(txt: str) -> Notice:
    """Lit un avis ; `classify(txt)` doit valoir « notice »."""
    portfolio = _portfolio(txt)
    if re.search(r"Transaction de fonds", txt):
        return _switch(txt, portfolio)
    qty, fund, isin = _fund(txt)
    kind: NoticeKind
    price = price_ccy = None
    detail = ""
    if re.search(r"Opération de bourse", txt):
        order = first(r"Ordre:\s+(Achat|Vente)\b", txt)
        if order is None:
            raise ViacError("viac.unrecognized", "ordre ni achat ni vente")
        kind = "buy" if order == "Achat" else "sell"
        if qty is None or isin is None:
            raise ViacError("viac.unrecognized", "parts ou ISIN absents")
        m = re.search(rf"Cours:\s+([A-Z]{{3}})\s+({NUM})", txt)
        if m:
            price_ccy, price = m.group(1), m.group(2)
        when, amount = _booked(
            rf"Montant comptabilis[ée]:\s+Valeur\s+({DATE})\s+CHF\s+({NUM})", txt
        )
    elif re.search(r"Avis de dividende", txt):
        kind = "dividend"
        detail = (first(r"Type de distribution:\s+(.+)", txt) or "").strip()
        m = re.search(rf"Distribution:\s+([A-Z]{{3}})\s+({NUM})", txt)
        if m:
            price_ccy, price = m.group(1), m.group(2)
        when, amount = _booked(rf"Montant crédité:\s+Valeur\s+({DATE})\s+CHF\s+({NUM})", txt)
    elif re.search(r"^\s*Intérêts\s*$", txt, re.M):
        kind = "interest"
        rate = first(r"Taux d.intérêt:\s+([\d.]+%)", txt) or ""
        period = first(r"Période d.intérêt:\s+(\S+)", txt) or ""
        detail = f"{rate} {period}".strip()
        m = re.search(rf"Montant crédité:\s+CHF\s+({NUM})", txt)
        on = first(rf"crédité le ({DATE})", txt) or first(rf"B[âa]le,\s+({DATE})", txt)
        if m is None or on is None:
            raise ViacError("viac.unrecognized", "montant ou date des intérêts absents")
        when, amount = iso(on), m.group(1)
    elif re.search(r"^\s*Commission\s*$", txt, re.M):
        kind = "fee"
        rate = first(r"p\.a\..*?:\s+([\d.]+%)", txt) or ""
        detail = f"taux effectif {rate}".strip()
        when, amount = _booked(FEE_BOOKED, txt)
    elif m := re.search(r"^\s*(Versement|Retrait)\b", txt, re.M):
        kind = "deposit" if m.group(1) == "Versement" else "withdrawal"
        when, amount = _booked(rf"(?:Valeur|Valuta)\s+({DATE})\s+CHF\s+({NUM})", txt)
    else:
        raise ViacError("viac.unrecognized", "type d'avis inconnu")
    value = abs(num(amount))
    if value == 0:
        raise ViacError("viac.unrecognized", "montant nul")
    quantity = num(qty) if qty is not None else None
    if quantity == 0 and kind in ("buy", "sell"):
        # petit achat de rééquilibrage : VIAC arrondit les parts à 2 décimales et imprime
        # « 0.00 parts ». Avec un cours en CHF, le montant comptabilisé donne les parts
        # réelles ; en devise, l'avis ne donne pas le taux : on garde le montant sans parts
        # (aucune ligne de titres), le rapport suivant donne les positions exactes
        if price is not None and price_ccy == "CHF" and num(price) > 0:
            with localcontext(DECIMAL_CONTEXT):
                quantity = (value / num(price)).quantize(
                    Decimal(1).scaleb(-QTY_PLACES), rounding=ROUND_HALF_EVEN
                )
        else:
            quantity = None
    if quantity is not None and quantity <= 0:
        raise ViacError("viac.unrecognized", "nombre de parts invalide")
    return Notice(
        kind=kind,
        portfolio=portfolio,
        value_date=when,
        amount=value,
        isin=isin,
        fund=fund,
        quantity=quantity,
        price=num(price) if price is not None else None,
        price_currency=price_ccy,
        detail=detail[:80],
    )
