"""Rapport VIAC « Rapport au JJ.MM.AAAA » (ticket L4-04), porté de `viac_rapport.py`.

Seul ce qui sert au patrimoine est repris : la récapitulation des portefeuilles (solde), et
pour chacun ses positions (quantité, ISIN, prix initial, cours, valeur en CHF) et son
« Compte 3a » de liquidités. Les répartitions par secteur et par région attendront la
transparence des fonds (lot 6). Les pages d'un portefeuille se reconnaissent à leur en-tête
`Récapitulation des titres "Nom"`.
"""

from __future__ import annotations

import re

from hub.domains.finance.sources.infra.viac import DATE, NUM, PORTFOLIO, ViacError, first, iso, num
from hub.domains.finance.sources.model.viac import PortfolioReport, Position, Report

CATEGORIES = ("Liquidités", "Actions", "Immobilier", "Matières premières", "Obligations")
_QUOTED = '["“«]\\s*{name}\\s*["”»]'
_RECAP = re.compile(
    rf"^\s*({PORTFOLIO})\s+(\S+)\s+(Stratégie \S+)\s+({NUM})\s+({NUM})%\s+({NUM})\s+({NUM})\s*$",
    re.M,
)
_CASH = re.compile(rf"^\s*Compte 3a\s+CHF\s+({NUM})\s+(.+?)\s{{2,}}({NUM})%\s+({NUM})\s*$")
_POSITION = re.compile(
    rf"^\s*(.+?)\s{{2,}}([A-Z]{{3}})\s+({NUM})\s+(.+?)\s{{2,}}([A-Z]{{2}}[A-Z0-9]{{10}})\s+"
    rf"({NUM})\s+({NUM})\s+({NUM})%\s+({NUM})%\s+({NUM})\s*$"
)


def section(txt: str, title: str, name: str) -> str:
    """Texte de toutes les pages dont l'en-tête contient `title "name"`."""
    head = re.compile(re.escape(title) + r"\s+" + _QUOTED.format(name=re.escape(name)))
    return "\n".join(p for p in txt.split("\f") if head.search(p))


def _positions(txt: str) -> tuple[list[Position], str | None]:
    out: list[Position] = []
    cash: str | None = None
    category: str | None = None
    for line in txt.splitlines():
        s = line.strip()
        if s in CATEGORIES:
            category = s
            continue
        m = _CASH.match(line)
        if m:
            cash = m.group(4)
            continue
        m = _POSITION.match(line)
        if m:
            out.append(
                Position(
                    category=category,
                    sub_class=m.group(1).strip(),
                    currency=m.group(2),
                    quantity=num(m.group(3)),
                    name=re.sub(r"\s{2,}", " ", m.group(4)).strip(),
                    isin=m.group(5),
                    cost_price=num(m.group(6)),
                    price=num(m.group(7)),
                    value=num(m.group(10)),
                    weight_pct=num(m.group(9)),
                )
            )
    return out, cash


def parse(txt: str) -> Report:
    on = first(rf"Rapport au ({DATE})", txt)
    if on is None:
        raise ViacError("viac.unrecognized", "date du rapport absente")
    generated = first(rf"Généré le ({DATE})", txt)
    portfolios: list[PortfolioReport] = []
    seen: set[str] = set()
    for m in _RECAP.finditer(txt):
        number, name = m.group(1), m.group(2)
        if number in seen:  # la récapitulation peut être répétée sur plusieurs pages
            continue
        seen.add(number)
        positions, cash = _positions(section(txt, "Récapitulation des titres", name))
        portfolios.append(
            PortfolioReport(
                number=number,
                name=name,
                strategy=m.group(3),
                deposits_year=num(m.group(4)),
                balance=num(m.group(7)),
                cash=num(cash) if cash is not None else None,
                positions=positions,
            )
        )
    if not portfolios:
        raise ViacError("viac.unrecognized", "aucun portefeuille dans le rapport")
    return Report(
        on_date=iso(on), generated_on=iso(generated) if generated else None, portfolios=portfolios
    )
