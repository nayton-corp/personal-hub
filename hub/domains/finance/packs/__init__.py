"""Packs pays (audit M17, m13) : tout ce qu'une instance sait de son pays sort des modules
génériques et tient ici, pays par pays.

Un pack porte la devise et le fuseau proposés à l'installation, la locale de l'app, les modules
qu'il ouvre (pilier 3a), la catégorie et les plafonds de l'épargne-retraite, les formats de
libellés de carte et les localités de la banque, les consignes de l'IA pour le classement, la
région domestique de la transparence des fonds. Le code générique lit `HUB_COUNTRY` ou le profil
et demande son pack (`packs.instance.current()`) ; un pays sans pack reçoit un pack vide, qui
ne sait rien de particulier. `base` est pur (le modèle du registre l'importe) ; `instance`
fait le lien avec le profil.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from hub.domains.finance.packs import ch
from hub.domains.finance.packs.base import (
    CARD,
    CASH,
    PAYMENT,
    CountryPack,
    LabelFormat,
    PersonPayment,
    Regions,
)

__all__ = [
    "CARD",
    "CASH",
    "CONTRIBUTIONS",
    "EMPTY",
    "PAYMENT",
    "CountryPack",
    "LabelFormat",
    "PersonPayment",
    "Regions",
    "available",
    "pack",
]

EMPTY = CountryPack(country="")


def available() -> dict[str, CountryPack]:
    return {ch.PACK.country: ch.PACK}


def pack(country: str | None) -> CountryPack:
    """Le pack du pays, ou un pack vide à son nom."""
    code = (country or "").strip().upper()
    return available().get(code) or replace(EMPTY, country=code)


# point d'entrée `hub.country_packs` : ce que le cœur sait des pays (profil, `hub init`)
CONTRIBUTIONS: dict[str, dict[str, Any]] = {c: p.contribution() for c, p in available().items()}
