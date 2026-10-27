"""Documents VIAC fictifs (lot 4), au format de `pdftotext -layout`.

Aucune donnée réelle : numéros de portefeuille, fonds, ISIN et montants inventés. Les textes
reprennent la mise en page que les motifs de `viac_parser.py` et `viac_rapport.py` lisent. Pour
les tests, un « PDF » est ce texte derrière un en-tête `%PDF-` ; `fake_text` le relit sans
poppler. `real_pdf` fabrique un vrai PDF d'une page, pour le test d'intégration avec
`pdftotext`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

PORTFOLIO = "3.100.200.300.01"
PORTFOLIO_2 = "3.100.200.300.02"
FUND_WORLD = ("Fonds Fictif Actions Monde", "CH0000000011")
FUND_CH = ("Fonds Fictif Actions Suisse", "CH0000000029")
FUND_RE = ("Fonds Fictif Immobilier Suisse", "CH0000000037")
HEADER = b"%PDF-1.4\n%fictif\n"


def d(day: date) -> str:
    return day.strftime("%d.%m.%Y")


def chf(amount: str) -> str:
    """'15240.12' -> "15'240.12", comme VIAC l'imprime."""
    units, _, cents = amount.partition(".")
    sign = "-" if units.startswith("-") else ""
    units = units.lstrip("-")
    groups = []
    while len(units) > 3:
        groups.insert(0, units[-3:])
        units = units[:-3]
    groups.insert(0, units)
    return sign + "'".join(groups) + (f".{cents}" if cents else "")


def _letter(title: str, portfolio: str, on: date, body: list[str]) -> str:
    return "\n".join(
        [
            "Fondation de prévoyance fictive 3a",
            "Case postale, 4002 Bâle",
            "",
            f"Bâle, {d(on)}",
            "",
            title,
            f"Portefeuille {portfolio}",
            "",
            *body,
            "",
            "Ce document est établi automatiquement et ne porte pas de signature.",
            "",
        ]
    )


def buy(
    on: date,
    qty: str,
    amount: str,
    fund: tuple[str, str] = FUND_WORLD,
    portfolio: str = PORTFOLIO,
    *,
    sell: bool = False,
    price: str | None = None,
    currency: str = "CHF",
) -> str:
    name, isin = fund
    price = price or "100.00"
    body = [
        f"Ordre: {'Vente' if sell else 'Achat'}",
        f"{qty} parts {name}",
        f"ISIN: {isin}",
        f"Cours: {currency} {chf(price)}",
        f"Montant {currency} {chf(amount)}",
    ]
    if currency != "CHF":
        body.append(f"Taux de conversion CHF/{currency} 0.8800")
    body.append(f"Montant comptabilisé: Valeur {d(on)} CHF {chf(amount)}")
    return _letter("Opération de bourse", portfolio, on, body)


def dividend(
    on: date, amount: str, fund: tuple[str, str] = FUND_CH, portfolio: str = PORTFOLIO
) -> str:
    name, isin = fund
    return _letter(
        "Avis de dividende",
        portfolio,
        on,
        [
            f"12.000 parts {name}",
            f"ISIN: {isin}",
            "Type de distribution: Distribution ordinaire",
            "Distribution: CHF 0.50",
            f"Montant crédité: Valeur {d(on)} CHF {chf(amount)}",
        ],
    )


def interest(on: date, amount: str, portfolio: str = PORTFOLIO) -> str:
    return _letter(
        "Intérêts",
        portfolio,
        on,
        [
            "Taux d'intérêt: 0.10%",
            "Période d'intérêt: 01.07.2026-30.09.2026",
            f"Le montant suivant vous a été crédité le {d(on)}.",
            f"Montant crédité: CHF {chf(amount)}",
        ],
    )


def fee(on: date, amount: str, portfolio: str = PORTFOLIO) -> str:
    return _letter(
        "Commission",
        portfolio,
        on,
        [
            "Commission de gestion p.a. (taux effectif):  0.44%",
            "Base de calcul: valeur moyenne CHF 10'000.00",
            f"Montant débité: Valuta {d(on)} CHF {chf(amount)}",
        ],
    )


def deposit(on: date, amount: str, portfolio: str = PORTFOLIO, *, withdrawal: bool = False) -> str:
    return _letter(
        "Retrait" if withdrawal else "Versement",
        portfolio,
        on,
        [f"Nous avons comptabilisé :   Valeur {d(on)} CHF {chf(amount)}"],
    )


def attestation(year: int, amount: str, portfolio: str = PORTFOLIO) -> str:
    """Attestation fiscale : cite les versements de l'année, n'en est pas un."""
    return _letter(
        f"Attestation fiscale {year}",
        portfolio,
        date(year + 1, 1, 15),
        [
            f"Versements {year}",
            f"Versement 3a déductible :   Valeur 31.12.{year} CHF {chf(amount)}",
        ],
    )


@dataclass
class Pos:
    qty: str
    value: str  # CHF
    fund: tuple[str, str] = FUND_WORLD
    sub_class: str = "Actions Monde"
    category: str = "Actions"
    currency: str = "CHF"
    cost_price: str = "100.00"
    price: str = "110.00"


@dataclass
class Folio:
    name: str
    number: str = PORTFOLIO
    cash: str = "0.00"
    positions: list[Pos] = field(default_factory=list)
    deposits_year: str = "7258.00"

    def balance(self) -> str:
        from decimal import Decimal

        total = Decimal(self.cash) + sum((Decimal(p.value) for p in self.positions), Decimal(0))
        return str(total)


def report(on: date, folios: list[Folio], generated: date | None = None) -> str:
    """Rapport au JJ.MM.AAAA : une page de récapitulation, puis une page « Récapitulation des
    titres » par portefeuille (pages séparées par un saut de page)."""
    from decimal import Decimal

    total = sum((Decimal(f.balance()) for f in folios), Decimal(0))
    recap = [
        "Rapport au " + d(on),
        "Généré le " + d(generated or on),
        "",
        "Récapitulation des portefeuilles",
        "Portefeuille               Nom        Stratégie          Versements   Rendement"
        "      Rendement CHF          Solde",
    ]
    for f in folios:
        recap.append(
            f"{f.number}   {f.name}   Stratégie Fictive100   {chf(f.deposits_year)}    "
            f"5.20%   {chf('312.40')}   {chf(f.balance())}"
        )
    recap.append(f"Total   {chf('7258.00')}   5.20%   {chf('312.40')}   {chf(str(total))}")
    pages = ["\n".join(recap)]
    for f in folios:
        lines = [f'Récapitulation des titres "{f.name}"', "", "Liquidités"]
        if f.cash != "0.00":
            lines.append(
                f"  Compte 3a   CHF   {chf(f.cash)}   Compte 3a {f.name}     1.00%   {chf(f.cash)}"
            )
        current = None
        for p in f.positions:
            if p.category != current:
                lines.append(p.category)
                current = p.category
            name, isin = p.fund
            lines.append(
                f"  {p.sub_class}   {p.currency}   {p.qty}   {name}   {isin}   "
                f"{chf(p.cost_price)}   {chf(p.price)}   10.00%   20.00%   {chf(p.value)}"
            )
        pages.append("\n".join(lines))
    return "\f".join(pages) + "\n"


def fake_pdf(txt: str) -> bytes:
    return HEADER + txt.encode()


def fake_text(data: bytes) -> str:
    """Remplace `pdftotext` dans les tests : relit le texte derrière l'en-tête."""
    from hub.domains.finance.viac import ViacError

    if not data.startswith(HEADER):
        raise ViacError("viac.unreadable", "PDF illisible")
    return data[len(HEADER) :].decode()


def real_pdf(txt: str) -> bytes:
    """Vrai PDF (une page par saut de page), police Courier, texte en latin-1."""
    pages = txt.split("\f")
    objs: list[bytes] = [b"<< /Type /Catalog /Pages 2 0 R >>", b""]
    kids = []
    font = 3
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier /Encoding /WinAnsiEncoding >>")
    for page in pages:
        lines = page.splitlines()
        esc = [x.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") for x in lines]
        stream = "BT /F1 7 Tf 9 TL 20 800 Td " + " ".join(f"({x}) '" for x in esc) + " ET"
        content = stream.encode("latin-1")
        objs.append(b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream")
        content_no = len(objs)
        objs.append(
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 842 842] /Contents %d 0 R "
            b"/Resources << /Font << /F1 %d 0 R >> >> >>" % (content_no, font)
        )
        kids.append(len(objs))
    objs[1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (
        b" ".join(b"%d 0 R" % k for k in kids),
        len(kids),
    )
    out = b"%PDF-1.4\n"
    offsets = []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return out
