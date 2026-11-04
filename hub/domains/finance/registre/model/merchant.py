"""Commerçant d'un libellé bancaire, pour regrouper « À classer » et nommer une règle.

Un paiement par carte n'a souvent pas de contrepartie (« NOTPROVIDED », ou le nom du titulaire
dans un ancien format) : le commerçant n'est que dans le libellé, entouré d'une date, d'une
heure, d'une ville et d'un numéro de carte. Grouper par libellé entier faisait un groupe par
achat. Les formats de libellés et les localités de la banque viennent du pack pays
(`packs.base.LabelFormat`, `CountryPack.cities`) ; sans pack, rien n'est reconnu.

La clé rendue est toujours un morceau du libellé normalisé (mots consécutifs) : « Toujours »
en fait le motif d'une règle, qui doit retrouver les achats suivants chez le même commerçant.
"""

from __future__ import annotations

import re

from hub.domains.finance.packs.base import CARD, CASH, CountryPack
from hub.kernel.text import normalize

_DIGITS = re.compile(r"\d+")
_STORE = re.compile(r"([a-z][a-z&'.]*)-\d+")  # « coop-1234 » : numéro de magasin collé
_TAIL = re.compile(r"^(?:\+?\d{6,}|\d+)$")  # téléphone ou numéro de transaction TWINT

# mots vides laissés en fin de nom une fois la ville coupée (« Garage de Bulle » → « garage »)
_STOP = frozenset({"de", "du", "des", "la", "le", "les", "l'", "d'", "a", "au", "sa", "ag"})


def _cut_city(zone: str, cities: frozenset[str]) -> str:
    """Zone « commerçant + ville » tronquée : coupe au premier mot qui est une localité, un
    numéro, ou, en dernier mot, le début d'une localité (« frib »)."""
    tokens = zone.split(" ")
    keep = tokens
    for i, raw in enumerate(tokens):
        t = raw.strip(",.-")
        store = _STORE.fullmatch(t)
        if store:
            keep = [*tokens[:i], store.group(1)] if i else [store.group(1)]
            break
        if i == 0:
            continue
        last = i == len(tokens) - 1
        if (
            _DIGITS.fullmatch(t)
            or t in cities
            or (last and len(t) >= 4 and any(c.startswith(t) for c in cities))
        ):
            keep = tokens[:i]
            break
    while len(keep) > 1 and keep[-1].strip(",.-") in _STOP:
        keep = keep[:-1]
    return " ".join(keep).rstrip(",.- ")


def key(label: str | None, pack: CountryPack) -> str | None:
    """Clé de commerçant du libellé selon les formats du pack, ou None si aucun ne le lit."""
    value = normalize(label)
    if not value:
        return None
    for fmt in pack.label_formats:
        found = fmt.regex().match(value)
        if not found:
            continue
        if fmt.kind == CARD:
            return _cut_city(found.group("m").strip(), pack.cities) or None
        if fmt.kind == CASH:
            return found.group("m")
        tokens = found.group("m").split(" ")
        while len(tokens) > 1 and _TAIL.fullmatch(tokens[-1].strip(",")):
            tokens = tokens[:-1]
        name = " ".join(tokens).rstrip(", ")
        return f"{found.group('prefix')} {name}" if name else None
    return None
