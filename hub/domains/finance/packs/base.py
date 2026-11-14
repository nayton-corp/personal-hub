"""La forme d'un pack pays : des données, aucune lecture (le modèle du registre l'importe)."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import cache
from typing import Any

CARD, CASH, PAYMENT = "card", "cash", "payment"


@dataclass(frozen=True)
class LabelFormat:
    """Un format de libellé bancaire, sur le texte normalisé (minuscules, sans accents). Le
    groupe `m` est le commerçant ; `kind` dit comment le lire : `card` (zone « commerçant
    ville », la ville en fin est coupée), `cash` (le motif lui-même est la clé), `payment`
    (groupe `prefix` puis un nom dont on retire les numéros de téléphone ou de transaction)."""

    pattern: str
    kind: str

    def regex(self) -> re.Pattern[str]:
        return _compiled(self.pattern)


@cache
def _compiled(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern)


@dataclass(frozen=True)
class Regions:
    """La transparence des fonds range les pays en régions ; la région domestique est à part
    de l'Europe (« Suisse » et « Europe (hors Suisse) ») quand le pack en nomme une."""

    home: str | None = None  # étiquette de la région domestique
    home_words: tuple[str, ...] = ()  # pays et mots (normalisés) qui la désignent
    europe: str = "Europe"  # étiquette de l'Europe


@dataclass(frozen=True)
class PersonPayment:
    """Un paiement mobile (TWINT) : le libellé commence par `prefix` ; il va à une personne
    seulement si le nom porte `mark` (« NOM, PRÉNOM »), sinon la catégorie `category` (argent
    envoyé à un particulier) est écartée des suggestions de l'IA."""

    prefix: str
    mark: str
    category: str

    def public(self) -> dict[str, str]:
        return {"prefix": self.prefix, "mark": self.mark, "category": self.category}


@dataclass(frozen=True)
class CountryPack:
    country: str
    locale: str = "fr"  # mise en forme des dates et des nombres dans l'app
    currency: str | None = None  # devise de base proposée par `hub init` ; None : à donner
    timezone: str | None = None  # fuseau proposé par `hub init`
    modules: frozenset[str] = frozenset()  # modules que le pays ouvre (`pillar3a`)
    pension_category: str | None = None  # catégorie de l'épargne-retraite plafonnée
    pension_caps: Mapping[int, int] = field(default_factory=dict)  # année → plafond (mineures)
    cities: frozenset[str] = frozenset()  # localités coupées en fin de libellé de carte
    label_formats: tuple[LabelFormat, ...] = ()  # formats de libellés de la banque du pays
    ai_context: str = "d'un compte bancaire"  # « d'un compte bancaire suisse »
    category_hints: Mapping[str, str] = field(default_factory=dict)  # catégorie → contenu
    person_payment: PersonPayment | None = None
    regions: Regions = field(default_factory=Regions)
    # pour l'app : commerçants du pays → pictogramme (motifs JavaScript, sur le nom en
    # minuscules), établissements → (sigle, teinte), catégories du pack → (pictogramme, teinte) ;
    # logos en couleur des commerçants (motif → logo) et des établissements (clé → logo), les
    # logos étant des fichiers de l'app (`web/logos/<logo>.svg`)
    merchant_icons: tuple[tuple[str, str], ...] = ()
    institution_marks: Mapping[str, tuple[str, str]] = field(default_factory=dict)
    merchant_logos: tuple[tuple[str, str], ...] = ()
    institution_logos: Mapping[str, str] = field(default_factory=dict)
    category_icons: Mapping[str, tuple[str, int]] = field(default_factory=dict)

    def pension_cap(self, year: int) -> int | None:
        """Le plafond de l'année, sinon le dernier connu avant elle, sinon le premier."""
        if not self.pension_caps:
            return None
        known = [y for y in self.pension_caps if y <= year] or [min(self.pension_caps)]
        return self.pension_caps[max(known)]

    def contribution(self) -> dict[str, Any]:
        """Ce que le cœur publie du pack (`hub.country_packs`) : les modules, la locale, la
        devise et le fuseau proposés, et pour les clients de l'API (`/profile`) les consignes
        de l'IA."""
        return {
            "modules": self.modules,
            "locale": self.locale,
            "currency": self.currency,
            "timezone": self.timezone,
            "public": {
                "ai_context": self.ai_context,
                "category_hints": dict(self.category_hints),
                "person_payment": self.person_payment.public() if self.person_payment else None,
                "merchant_icons": [list(x) for x in self.merchant_icons],
                "institution_marks": {k: list(v) for k, v in self.institution_marks.items()},
                "merchant_logos": [list(x) for x in self.merchant_logos],
                "institution_logos": dict(self.institution_logos),
                "category_icons": {k: list(v) for k, v in self.category_icons.items()},
            },
        }
