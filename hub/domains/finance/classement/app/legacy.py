"""Reprise des règles de `bcf_aggregate.py` (ticket L3-01).

L'ancien script catégorisait dans cet ordre : virement vers un de mes comptes (IBAN), puis
destination d'épargne ou de virement (mots-clés, dans les deux sens), puis pour un crédit
salaire, remboursement ou autre revenu, puis pour un débit les catégories dans l'ordre du
fichier, TWINT entre particuliers et virements à qualifier. Le reste n'avait pas de catégorie.

Cet ordre devient la priorité des règles. Le fichier personnel (`bcf_rules.json`) se reprend
avec `hub finance rules import-legacy`, qui n'affiche que des compteurs. Les règles de départ
d'une base neuve viennent des packs (`packs.py`), découpés du fichier de départ du script.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Connection, text

from hub.domains.finance.classement.app import rules
from hub.kernel.text import normalize

# nom de l'ancien script -> (identifiant, nom, groupe) dans le hub
CATEGORY_MAP: dict[str, tuple[str, str, str]] = {
    "Logement": ("logement", "Logement", "fixed"),
    "Assurances": ("assurances", "Assurances", "fixed"),
    "Impôts": ("impots", "Impôts", "fixed"),
    "Transports": ("transports", "Transports", "variable"),
    "Abonnements": ("abonnements", "Abonnements", "fixed"),
    "Alimentation": ("alimentation", "Alimentation", "variable"),
    "Restaurants & sorties": ("restaurants", "Restaurants et sorties", "variable"),
    "Loisirs & sport": ("loisirs", "Loisirs et sport", "variable"),
    "Santé": ("sante", "Santé", "variable"),
    "Shopping": ("shopping", "Shopping", "variable"),
    "Vacances": ("voyages", "Vacances", "variable"),
    "Cadeaux & dons": ("cadeaux", "Cadeaux et dons", "variable"),
    "Frais bancaires": ("frais-bancaires", "Frais bancaires", "fixed"),
    "Retrait cash": ("retraits", "Retraits d'espèces", "variable"),
    "Soins & beauté": ("soins", "Soins et beauté", "variable"),
    "Formation & outils": ("formation", "Formation et outils", "variable"),
    "TWINT entre particuliers": ("twint-particuliers", "TWINT entre particuliers", "variable"),
    "Virements à des particuliers": (
        "virements-particuliers",
        "Virements à des particuliers",
        "variable",
    ),
    "Virements à qualifier": ("a-qualifier", "Virements à qualifier", "variable"),
    "Salaire": ("salaire", "Salaire", "income"),
    "Remboursements": ("remboursements", "Remboursements", "income"),
    "Autres revenus": ("autres-revenus", "Autres revenus", "income"),
}
TRANSFER_MAP: dict[str, tuple[str, str, str]] = {
    "Entre mes comptes": ("transfer-own", "Virement entre mes comptes", "transfer"),
    "Mes autres comptes": ("transfer-own", "Virement entre mes comptes", "transfer"),
    "VIAC 3a": ("epargne-3a", "Pilier 3a", "savings"),
    "IBKR": ("investissements", "Investissements", "savings"),
    "Crypto (exchange)": ("crypto", "Crypto", "savings"),
    "Revolut": ("transfer-revolut", "Vers Revolut", "transfer"),
    "Raiffeisen": ("transfer-raiffeisen", "Vers Raiffeisen", "transfer"),
}

# mots-clés codés en dur dans categorize() de l'ancien script
SALARY = ("salaire", "salary", "lohn", "traitement")
REFUNDS = ("rembours", "remboursement", "retour", "refund")
TWINT = ("débit twint",)  # « twint » et « débit/debit twint » : le second suffit, normalisé
TO_QUALIFY = ("ordre permanent", "ordre e-banking", "mobile banking", "virement")

# priorités : le système (0) passe avant tout
P_TRANSFERS = 10
P_SALARY = 20
P_REFUNDS = 21
P_OTHER_INCOME = 29
P_CATEGORIES = 100
P_TWINT = 200
P_TO_QUALIFY = 210

_SLUG = re.compile(r"[^a-z0-9]+")


class LegacyError(ValueError):
    pass


@dataclass(frozen=True)
class Spec:
    """Une règle reprise, avant insertion."""

    field: str
    pattern: str
    direction: str
    category_id: str
    priority: int

    def id(self, prefix: str) -> str:
        return rules.rule_id(prefix, self.field, self.pattern, self.direction, self.category_id)


@dataclass(frozen=True)
class NewCategory:
    id: str
    name: str
    grp: str


def slug(name: str) -> str:
    value = _SLUG.sub("-", normalize(name)).strip("-")[:40]
    return value if len(value) >= 2 else f"cat-{value or 'x'}"


def _target(
    name: str, mapping: Mapping[str, tuple[str, str, str]], grp: str
) -> tuple[str, str, str]:
    return mapping.get(name) or (slug(name), name, grp)


def _keywords(values: object, where: str) -> list[str]:
    if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
        raise LegacyError(f"{where} : liste de mots-clés attendue")
    return list(values)


def convert(data: Mapping[str, Any]) -> tuple[list[Spec], list[NewCategory]]:
    """Fichier de l'ancien script -> règles ordonnées et catégories nécessaires."""
    cats = data.get("categories")
    transfers = data.get("transfers", {})
    if not isinstance(cats, dict) or not isinstance(transfers, dict):
        raise LegacyError("format inattendu : clés « categories » et « transfers »")
    specs: list[Spec] = []
    needed: dict[str, NewCategory] = {}

    def add(kws: Iterable[str], direction: str, target: tuple[str, str, str], prio: int) -> None:
        needed.setdefault(target[0], NewCategory(*target))
        seen = set()
        for kw in kws:
            pattern = rules.normalize_pattern("search_text", kw)
            if not pattern.strip() or pattern in seen:
                continue  # « régie » et « regie » donnent le même motif
            seen.add(pattern)
            specs.append(Spec("search_text", pattern, direction, target[0], prio))

    for i, (name, kws) in enumerate(transfers.items()):
        words = _keywords(kws, f"transfers.{i}")
        add(words, "any", _target(name, TRANSFER_MAP, "transfer"), P_TRANSFERS + i)
    add(SALARY, "credit", CATEGORY_MAP["Salaire"], P_SALARY)
    add(REFUNDS, "credit", CATEGORY_MAP["Remboursements"], P_REFUNDS)
    other = CATEGORY_MAP["Autres revenus"]
    needed.setdefault(other[0], NewCategory(*other))
    specs.append(Spec("search_text", "", "credit", other[0], P_OTHER_INCOME))
    for i, (name, kws) in enumerate(cats.items()):
        words = _keywords(kws, f"categories.{i}")
        add(words, "debit", _target(name, CATEGORY_MAP, "variable"), P_CATEGORIES + i)
    add(TWINT, "debit", CATEGORY_MAP["TWINT entre particuliers"], P_TWINT)
    add(TO_QUALIFY, "debit", CATEGORY_MAP["Virements à qualifier"], P_TO_QUALIFY)
    return specs, list(needed.values())


@dataclass
class ImportReport:
    rules_added: int = 0
    rules_kept: int = 0
    rules_disabled: int = 0
    categories_added: int = 0
    own_ibans_ignored: int = 0
    categorized: int = 0
    version: int = 0

    def public(self) -> dict[str, int]:
        return dict(self.__dict__)


def ensure_categories(conn: Connection, needed: Iterable[NewCategory]) -> int:
    added = 0
    for c in needed:
        found = conn.execute(text("SELECT 1 FROM categories WHERE id = :i"), {"i": c.id}).first()
        if found is None:
            conn.execute(
                text("INSERT INTO categories (id, name, grp) VALUES (:i, :n, :g)"),
                {"i": c.id, "n": c.name, "g": c.grp},
            )
            added += 1
    return added


def import_rules(conn: Connection, data: Mapping[str, Any], *, run: bool = True) -> ImportReport:
    """Aligne les règles reprises sur le fichier : ajoute ce qui manque, désactive les règles de
    départ (« seed- ») et reprises (« legacy- ») absentes du fichier ; garde les autres."""
    specs, needed = convert(data)
    report = ImportReport(own_ibans_ignored=len(data.get("own_ibans") or []))
    report.categories_added = ensure_categories(conn, needed)
    existing = {r.id: r for r in rules.list_rules(conn)}
    by_shape = {
        (r.field, r.pattern, r.direction, r.category_id): r
        for r in existing.values()
        if r.id.startswith(("seed-", "legacy-"))
    }
    wanted: set[str] = set()
    for s in specs:
        found = by_shape.get((s.field, s.pattern, s.direction, s.category_id))
        if found is not None:
            wanted.add(found.id)
            if not found.active or found.priority != s.priority:
                conn.execute(
                    text("UPDATE rules SET active = 1, priority = :p WHERE id = :i"),
                    {"p": s.priority, "i": found.id},
                )
            report.rules_kept += 1
            continue
        new_id = s.id("legacy")
        wanted.add(new_id)
        rules.insert_rule(
            conn,
            id=new_id,
            field=s.field,
            pattern=s.pattern,
            direction=s.direction,
            category_id=s.category_id,
            priority=s.priority,
        )
        report.rules_added += 1
    for r in by_shape.values():
        if r.id not in wanted and r.active:
            rules.set_active(conn, r.id, False)
            report.rules_disabled += 1
    report.version = rules.bump_version(conn)
    if run:
        report.categorized = rules.run(conn)
    return report
