"""Commerçant d'un libellé bancaire, pour regrouper « À classer » et nommer une règle.

Les paiements par carte BCF n'ont pas de contrepartie (« NOTPROVIDED », ou le nom du titulaire
dans l'ancien format) : le commerçant n'est que dans le libellé, entouré d'une date, d'une heure,
d'une ville et d'un numéro de carte. Grouper par libellé entier faisait un groupe par achat.

La clé rendue est toujours un morceau du libellé normalisé (mots consécutifs) : « Toujours »
en fait le motif d'une règle, qui doit retrouver les achats suivants chez le même commerçant.

Formats reconnus (gabarits relevés sur les exports BCF, sans donnée réelle) :
- « Paiement jj.mm.aaaa hh:mm COMMERÇANTVILLE Numéro de carte: … » (zone tronquée, ville collée)
- « Paiement - COMMERÇANT, VILLE - … - N° carte … » (ancien format)
- « Remboursement [manuel] - COMMERÇANT, VILLE - … »
- « Débit direct Maestro hh:mm COMMERÇANT VILLE Numéro de carte: … »
- « Retrait BM … » et « Prélèvement bancomat … » (un groupe chacun)
- « Débit TWINT NOM, PRÉNOM, +41… » ou « Débit TWINT COMMERÇANT 1234… », « Crédit TWINT … »
"""

from __future__ import annotations

import re

from hub.kernel.text import normalize

_CARD = re.compile(r"^paiement \d\d\.\d\d\.\d{4} \d\d:\d\d (.+?) numero de carte\b")
_MAESTRO = re.compile(r"^debit direct maestro \d\d:\d\d (.+?) numero de carte\b")
_CARD_OLD = re.compile(r"^(paiement|remboursement(?: manuel)?) - (.+?)(?:, | - )")
_CASH = re.compile(r"^(retrait bm|prelevement bancomat)\b")
_TWINT = re.compile(r"^(debit|credit) twint (.+)$")
_DIGITS = re.compile(r"\d+")
_STORE = re.compile(r"([a-z][a-z&'.]*)-\d+")  # « coop-1234 » : numéro de magasin collé
_TAIL = re.compile(r"^(?:\+?\d{6,}|\d+)$")  # téléphone ou numéro de transaction TWINT

# mots vides laissés en fin de nom une fois la ville coupée (« Garage de Bulle » → « garage »)
_STOP = frozenset({"de", "du", "des", "la", "le", "les", "l'", "d'", "a", "au", "sa", "ag"})

# localités suisses courantes (romandes d'abord) et quelques villes étrangères fréquentes sur
# les achats en ligne ; une seule forme normalisée par mot, les noms composés avec leurs tirets
CITIES = frozenset(
    """
    fribourg freiburg bulle marly villars-sur-glane givisiez granges-paccot duedingen dudingen
    guin morat murten payerne romont estavayer estavayer-le-lac chatel-st-denis
    chatel-saint-denis avry avry-sur-matran matran belfaux courtepin tafers tavel schmitten
    wunnewil flamatt kerzers chiètres chietres plaffeien ueberstorf corminboeuf neyruz
    farvagny rossens le-mouret praroman broc gruyeres charmey la-roche riaz vuadens
    vaulruz semsales attalens oron palezieux moudon lucens yverdon yverdon-les-bains
    grandson orbe vallorbe sainte-croix lausanne renens prilly crissier bussigny ecublens
    morges nyon gland rolle aubonne coppet vevey montreux la-tour-de-peilz blonay aigle
    bex villars monthey martigny sion sierre crans-montana verbier saxon fully conthey
    visp brig zermatt geneve genf carouge meyrin vernier lancy onex thonex chene-bourg
    plan-les-ouates versoix neuchatel la-chaux-de-fonds le-locle peseux colombier boudry
    marin-epagnier cernier fleurier delemont porrentruy moutier bienne biel nidau lyss
    aarberg ins erlach tavannes saint-imier tramelan bern berne koniz ostermundigen
    muri ittigen worb munsingen thun spiez interlaken burgdorf langenthal solothurn
    soleure grenchen olten aarau baden wettingen brugg lenzburg zofingen basel bale
    allschwil riehen muttenz pratteln liestal luzern lucerne kriens emmen zug baar cham
    schwyz altdorf sarnen stans zurich zuerich winterthur uster dubendorf dietikon
    wallisellen kloten opfikon bulach horgen thalwil wadenswil meilen kusnacht
    schlieren regensdorf affoltern st-gallen st.gallen gossau wil rapperswil
    rapperswil-jona herisau appenzell frauenfeld kreuzlingen arbon weinfelden
    schaffhausen chur davos st-moritz klosters glarus bellinzona lugano locarno
    mendrisio chiasso ascona vaduz
    paris lyon annecy annemasse thonon evian besancon pontarlier mulhouse strasbourg
    london dublin cork amsterdam luxembourg bruxelles brussels berlin munchen muenchen
    hamburg frankfurt konstanz milano milan roma torino como madrid barcelona lisboa
    stockholm copenhagen kobenhavn oslo helsinki praha wien vienna warszawa luxemburg
    """.split()  # noqa: SIM905 - liste longue, plus lisible en texte
)


def _cut_city(zone: str) -> str:
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
            or t in CITIES
            or (last and len(t) >= 4 and any(c.startswith(t) for c in CITIES))
        ):
            keep = tokens[:i]
            break
    while len(keep) > 1 and keep[-1].strip(",.-") in _STOP:
        keep = keep[:-1]
    return " ".join(keep).rstrip(",.- ")


def key(label: str | None) -> str | None:
    """Clé de commerçant du libellé, ou None si le format n'est pas reconnu."""
    value = normalize(label)
    if not value:
        return None
    for pattern in (_CARD, _MAESTRO):
        found = pattern.match(value)
        if found:
            return _cut_city(found.group(1)) or None
    found = _CARD_OLD.match(value)
    if found:
        return _cut_city(found.group(2).strip()) or None
    found = _CASH.match(value)
    if found:
        return found.group(1)
    found = _TWINT.match(value)
    if found:
        tokens = found.group(2).split(" ")
        while len(tokens) > 1 and _TAIL.fullmatch(tokens[-1].strip(",")):
            tokens = tokens[:-1]
        name = " ".join(tokens).rstrip(", ")
        return f"{found.group(1)} twint {name}" if name else None
    return None
