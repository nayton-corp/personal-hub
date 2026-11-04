"""Le pack de la Suisse : franc, Zurich, fr-CH, pilier 3a et ses plafonds, les libellés de carte
de la BCF, les localités romandes puis suisses, les consignes de l'IA, « Suisse » à part de
l'Europe dans la transparence des fonds."""

from __future__ import annotations

from hub.domains.finance.packs.base import (
    CARD,
    CASH,
    PAYMENT,
    CountryPack,
    LabelFormat,
    PersonPayment,
    Regions,
)

# Formats relevés sur les exports BCF (gabarits, sans donnée réelle), sur le libellé normalisé :
# - « Paiement jj.mm.aaaa hh:mm COMMERÇANTVILLE Numéro de carte: … » (zone tronquée, ville collée)
# - « Débit direct Maestro hh:mm COMMERÇANT VILLE Numéro de carte: … »
# - « Paiement - COMMERÇANT, VILLE - … - N° carte … » et « Remboursement [manuel] - … » (ancien)
# - « Retrait BM … » et « Prélèvement bancomat … » (un groupe chacun)
# - « Débit TWINT NOM, PRÉNOM, +41… » ou « Débit TWINT COMMERÇANT 1234… », « Crédit TWINT … »
LABEL_FORMATS = (
    LabelFormat(r"^paiement \d\d\.\d\d\.\d{4} \d\d:\d\d (?P<m>.+?) numero de carte\b", CARD),
    LabelFormat(r"^debit direct maestro \d\d:\d\d (?P<m>.+?) numero de carte\b", CARD),
    LabelFormat(r"^(?:paiement|remboursement(?: manuel)?) - (?P<m>.+?)(?:, | - )", CARD),
    LabelFormat(r"^(?P<m>retrait bm|prelevement bancomat)\b", CASH),
    LabelFormat(r"^(?P<prefix>(?:debit|credit) twint) (?P<m>.+)$", PAYMENT),
)

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

# ce que contient une catégorie courante, pour que le modèle ne devine pas sur le seul nom
CATEGORY_HINTS = {
    "alimentation": "courses, supermarché, épicerie, kiosque, boulangerie, y compris en gare",
    "restaurants": "restaurant, café, bar, fast-food, livraison de repas",
    "transports": "billets de train ou de bus, carburant, parking, péage, taxi, vélo",
    "voiture-frais": "garage, entretien, pneus, assurance et impôt du véhicule",
    "voiture-credit": "mensualité du crédit ou du leasing de la voiture",
    "shopping": "habits, électronique, maison, grands magasins, achats en ligne",
    "loisirs": "sport, cinéma, concerts, jeux, sorties culturelles",
    "voyages": "hôtel, vol, location de vacances, dépenses de voyage",
    "abonnements": "streaming, téléphone, internet, logiciels facturés chaque mois",
    "sante": "pharmacie, médecin, dentiste, opticien",
    "soins": "coiffeur, esthétique",
    "retraits": "retrait d'espèces au bancomat",
    "twint-particuliers": "argent envoyé à une personne (jamais un commerce)",
}

# commerçants et prestataires suisses → pictogramme, pour l'app (les marques internationales
# restent dans le front) ; motifs JavaScript, testés sur le nom en minuscules
MERCHANT_ICONS = (
    (r"\b(migros|coop(?! ?bau)|denner|spar|volg|aligro|landi)", "cart"),
    (r"smood|eat\.ch", "utensils"),
    (r"\b(sbb|cff|ffs|tpg|tpf|bls|postauto|car postal|mobility|publibike|tl lausanne)", "train"),
    (r"\b(avia|tamoil|socar|agrola|migrol)\b", "fuel"),
    (r"parkingpay", "parking"),
    (r"amag|emil frey", "car"),
    (r"swiss intl|swiss int|edelweiss", "plane"),
    (r"blue tv|teleclub", "play"),
    (r"swisscom|sunrise|init7|quickline|upc|green\.ch", "wifi"),
    (r"\bsalt\b|wingo|yallo|lebara|m-budget mobile|digital republic", "phone"),
    (r"galaxus|digitec|ricardo|la poste|post ch|brack", "box"),
    (r"manor|globus|ochsner|vögele|bucherer", "bag"),
    (r"amavita|sun ?store|benu|drogerie|dropa|toppharm", "cross"),
    (r"hirslanden", "heart"),
    (r"basic-fit|update fitness|activ fitness", "dumbbell"),
    (r"path[eé]|ticketcorner|starticket|eventfrog", "ticket"),
    (r"bancomat|postomat", "banknote"),
    (r"twint", "swap"),
    (r"administration fiscale|service des contributions|\bafc\b", "landmark"),
    (
        r"helvetia|mobili[eè]re|zurich ins|baloise|\bcss\b|helsana|groupe mutuel|swica|sanitas"
        r"|visana|assura|concordia|sympany|\bkpt|atupri|vaudoise",
        "shield",
    ),
    (r"r[eé]gie|g[eé]rance|hornbach|jumbo|\bobi\b|coop bau|do it", "home"),
    (r"groupe e\b|romande energie|\bsig\b|\bewz\b|\bbkw\b", "bolt"),
    (r"serafe|billag", "receipt"),
    (r"payot|orell|thalia|epfl|unil|unige|hes-so", "book"),
    (r"fressnapf|qualipet", "paw"),
    (r"viac|frankly|finpension", "piggy"),
    (r"swissquote", "trend"),
    (r"swissborg", "coin"),
)

# établissements suisses : sigle court et teinte (jeton CSS du thème)
INSTITUTION_MARKS = {
    "bcf": ("BCF", "s2"),
    "viac": ("VIAC", "s1"),
    "postfinance": ("PF", "s3"),
    "ubs": ("UBS", "neg"),
    "raiffeisen": ("R", "neg"),
    "yuh": ("yuh", "s4"),
    "neon": ("N", "s2"),
    "frankly": ("F", "s1"),
    "finpension": ("fp", "s5"),
    "swissquote": ("SQ", "s3"),
    "swissborg": ("SB", "s2"),
    "bcv": ("BCV", "s2"),
    "bcge": ("BCGE", "neg"),
}

# catégories propres au pack de règles suisse : pictogramme et rang de teinte
CATEGORY_ICONS = {"twint-particuliers": ("swap", 6)}

PACK = CountryPack(
    country="CH",
    locale="fr-CH",
    currency="CHF",
    timezone="Europe/Zurich",
    modules=frozenset({"pillar3a"}),
    pension_category="epargne-3a",
    # plafond du 3e pilier A pour un salarié affilié à une caisse de pension, en centimes ;
    # `[finance] pillar3a_cap_minor` le remplace
    pension_caps={2024: 705_600, 2025: 725_800, 2026: 725_800},
    cities=CITIES,
    label_formats=LABEL_FORMATS,
    ai_context="d'un compte bancaire suisse",
    category_hints=CATEGORY_HINTS,
    person_payment=PersonPayment(prefix="debit twint ", mark=",", category="twint-particuliers"),
    merchant_icons=MERCHANT_ICONS,
    institution_marks=INSTITUTION_MARKS,
    category_icons=CATEGORY_ICONS,
    regions=Regions(
        home="Suisse",
        home_words=("switzerland", "suisse", "schweiz", "ch"),
        europe="Europe (hors Suisse)",
    ),
)
