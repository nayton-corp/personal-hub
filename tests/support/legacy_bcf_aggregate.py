# ruff: noqa
# mypy: ignore-errors
"""Oracle du ticket L3-01 : `DEFAULT_RULES`, `entries_of()` et `categorize()` copiés tels quels
de l'ancien script `bcf_aggregate.py` (version du 27 octobre 2026, sans aucune donnée). Les tests
comparent ses catégories à celles du moteur de règles sur les mêmes relevés fictifs.
"""

import re, xml.etree.ElementTree as ET

DEFAULT_RULES = {
    "categories": {
        "Logement": ["loyer", "régie", "regie", "immobilier", "hypoth"],
        "Assurances": [
            "assurance",
            "groupe mutuel",
            "assura",
            "css",
            "helsana",
            "swica",
            "sanitas",
            "visana",
            "concordia",
            "mobiliere",
            "mobilière",
            "axa",
            "zurich",
            "vaudoise",
            "allianz",
            "generali",
            "baloise",
            "bâloise",
            "helvetia",
        ],
        "Impôts": [
            "impôt",
            "impot",
            "administration cantonale",
            "etat de fribourg",
            "état de fribourg",
            "commune de",
            "ville de fribourg",
            "taxe",
        ],
        "Transports": [
            "tpf",
            "cff",
            "sbb",
            "leasing",
            "garage",
            "essence",
            "eni ",
            "shell",
            "bp ",
            "avia",
            "migrol",
            "socar",
            "tamoil",
            "coop pronto",
            "parking",
            "autoroute",
            "ofrou",
            "vignette",
            "mobility",
            "uber",
            "taxi",
            "wielandbus",
            "lim*ride",
            "lime",
            "fairtiq",
            "bolt",
            "publibike",
            "velo",
            "vélo",
            "cyclo",
        ],
        "Abonnements": [
            "netflix",
            "spotify",
            "swisscom",
            "sunrise",
            "salt",
            "wingo",
            "yallo",
            "apple.com",
            "icloud",
            "google",
            "disney",
            "amazon prime",
            "serafe",
            "billag",
            "youtube",
            "openai",
            "chatgpt",
            "claude",
            "anthropic",
            "blizzard",
            "splice",
            "adobe",
            "microsoft",
            "dropbox",
            "canva",
            "twitch",
            "patreon",
        ],
        "Alimentation": [
            "migros",
            "coop",
            "aldi",
            "lidl",
            "denner",
            "manor food",
            "volg",
            "landi",
            "boulangerie",
            "boucherie",
            "laiterie",
            "fromagerie",
            "marché",
            "epicerie",
            "épicerie",
            "bahnhofkiosk",
            "kkiosk",
            "kiosk",
            "selecta",
            "avec ",
        ],
        "Restaurants & sorties": [
            "restaurant",
            "café",
            "cafe",
            "caf ",
            "bar ",
            "pizzeria",
            "kebab",
            "mcdonald",
            "burger",
            "starbucks",
            "uber eats",
            "smood",
            "eat.ch",
            "just eat",
            "tea-room",
            "brasserie",
            "bistro",
            "sushi",
            "take away",
            "takeaway",
            "le port",
            "nouveau monde",
            "city fribourg",
            "le xxe",
            "buvette",
            "aigle noir",
            "crêperie",
            "creperie",
            "trentenaires",
            "lapart",
            "fri-son",
            "fricent",
            "ptite ruelle",
            "pub ",
            "lounge",
            "club ",
        ],
        "Loisirs & sport": [
            "fitness",
            "piscine",
            "cinema",
            "cinéma",
            "steam",
            "playstation",
            "nintendo",
            "decathlon",
            "ochsner",
            "ski",
            "remontées",
            "concert",
            "ticketcorner",
            "billetterie",
            "musée",
            "musee",
            "theatre",
            "théâtre",
        ],
        "Santé": [
            "pharmacie",
            "amavita",
            "sun store",
            "sunstore",
            "dr ",
            "dr.",
            "cabinet",
            "hopital",
            "hôpital",
            "hfr",
            "dentiste",
            "physio",
            "opticien",
            "visilab",
            "fielmann",
        ],
        "Shopping": [
            "zalando",
            "digitec",
            "galaxus",
            "microspot",
            "h&m",
            "ikea",
            "manor",
            "interdiscount",
            "fnac",
            "amazon",
            "temu",
            "shein",
            "jumbo",
            "hornbach",
            "bauhaus",
            "ochsner shoes",
            "dosenbach",
            "zara",
            "c&a",
            "freevap",
            "clutchcollect",
            "aliexpress",
            "ebay",
            "ricardo",
            "tutti",
        ],
        "Vacances": [
            "airbnb",
            "booking",
            "swiss",
            "easyjet",
            "ryanair",
            "hotel",
            "hôtel",
            "camping",
            "sncf",
            "trenitalia",
            "lufthansa",
            "edelweiss",
        ],
        "Cadeaux & dons": [
            "cadeau",
            "don ",
            "fleurs",
            "interflora",
            "fondation de france",
            "croix-rouge",
            "wwf",
            "caritas",
        ],
        "Frais bancaires": ["frais", "commission", "intérêts débiteurs"],
        "Retrait cash": [
            "bancomat",
            "retrait",
            "atm ",
            "postomat",
            "prélèvement en espèces",
            "prelevement en especes",
        ],
        "Soins & beauté": [
            "coiffeur",
            "coiffure",
            "créa-tifs",
            "crea-tifs",
            "barber",
            "esthéti",
            "estheti",
        ],
        "Formation & outils": [
            "superprof",
            "udemy",
            "coursera",
            "creately",
            "cursor",
            "github",
            "jetbrains",
            "notion",
        ],
        "TWINT entre particuliers": [],
    },
    "own_ibans": [],
    "transfers": {
        "VIAC 3a": ["terzo", "viac"],
        "IBKR": ["interactive brokers", "ibkr"],
        "Revolut": ["revolut"],
        "Raiffeisen": ["raiffeisen"],
        "Crypto (exchange)": ["swissborg", "kraken", "binance", "coinbase", "relai", "bity"],
    },
}

NS = {"c": "urn:iso:std:iso:20022:tech:xsd:camt.053.001.04"}


def find_ns(root):
    m = re.match(r"\{(.+)\}", root.tag)
    return {"c": m.group(1)} if m else NS


def text(el, path, ns):
    x = el.find(path, ns)
    return x.text.strip() if x is not None and x.text else ""


def entries_of(path):
    tree = ET.parse(path)
    root = tree.getroot()
    ns = find_ns(root)
    out = []
    accounts = []
    for stmt in root.iter(f"{{{ns['c']}}}Stmt"):
        iban = text(stmt, "c:Acct/c:Id/c:IBAN", ns)
        ccy = text(stmt, "c:Acct/c:Ccy", ns)
        closing = None
        for bal in stmt.findall("c:Bal", ns):
            if text(bal, "c:Tp/c:CdOrPrtry/c:Cd", ns) == "CLBD":
                amt = float(text(bal, "c:Amt", ns) or 0)
                sign = -1 if text(bal, "c:CdtDbtInd", ns) == "DBIT" else 1
                closing = {"amount": sign * amt, "date": text(bal, "c:Dt/c:Dt", ns)}
        accounts.append({"iban": iban, "currency": ccy, "closing": closing})
        for ntry in stmt.findall("c:Ntry", ns):
            amt = float(text(ntry, "c:Amt", ns) or 0)
            sign = -1 if text(ntry, "c:CdtDbtInd", ns) == "DBIT" else 1
            bdate = text(ntry, "c:BookgDt/c:Dt", ns) or text(ntry, "c:ValDt/c:Dt", ns)
            ref = text(ntry, "c:AcctSvcrRef", ns) or text(ntry, "c:NtryRef", ns)
            info = text(ntry, "c:AddtlNtryInf", ns)
            txs = ntry.findall("c:NtryDtls/c:TxDtls", ns)

            def tx_record(tx, k):
                cdtr, dbtr, ustrd = [], [], []
                for p in (
                    "c:RltdPties/c:Cdtr/c:Nm",
                    "c:RltdPties/c:Cdtr/c:Pty/c:Nm",
                    "c:RltdPties/c:UltmtCdtr/c:Nm",
                    "c:RltdPties/c:UltmtCdtr/c:Pty/c:Nm",
                ):
                    t = text(tx, p, ns)
                    if t:
                        cdtr.append(t)
                for p in (
                    "c:RltdPties/c:Dbtr/c:Nm",
                    "c:RltdPties/c:Dbtr/c:Pty/c:Nm",
                    "c:RltdPties/c:UltmtDbtr/c:Nm",
                    "c:RltdPties/c:UltmtDbtr/c:Pty/c:Nm",
                ):
                    t = text(tx, p, ns)
                    if t:
                        dbtr.append(t)
                for u in tx.findall("c:RmtInf/c:Ustrd", ns):
                    if u.text:
                        ustrd.append(u.text.strip())
                cp = text(tx, "c:RltdPties/c:CdtrAcct/c:Id/c:IBAN", ns) or text(
                    tx, "c:RltdPties/c:DbtrAcct/c:Id/c:IBAN", ns
                )
                tinfo = text(tx, "c:AddtlTxInf", ns)
                tamt = float(
                    text(tx, "c:Amt", ns)
                    or text(tx, "c:AmtDtls/c:TxAmt/c:Amt", ns)
                    or text(tx, "c:AmtDtls/c:InstdAmt/c:Amt", ns)
                    or 0
                )
                tsign = (
                    -1
                    if (text(tx, "c:CdtDbtInd", ns) or ("DBIT" if sign < 0 else "CRDT")) == "DBIT"
                    else 1
                )
                tref = (
                    text(tx, "c:Refs/c:AcctSvcrRef", ns)
                    or text(tx, "c:Refs/c:EndToEndId", ns)
                    or f"{ref}#{k}"
                )
                parties = cdtr if tsign < 0 else dbtr
                label = " | ".join(x for x in [tinfo or info] + parties + ustrd if x)
                return {
                    "iban": iban,
                    "date": bdate,
                    "amount": tsign * tamt,
                    "label": label,
                    "ref": tref,
                    "cp_iban": cp,
                }

            if len(txs) > 1:
                recs = [tx_record(tx, k) for k, tx in enumerate(txs)]
                if abs(sum(r["amount"] for r in recs) - sign * amt) < 0.05 or all(
                    r["amount"] for r in recs
                ):
                    out.extend(recs)
                    continue
            if len(txs) == 1:
                r = tx_record(txs[0], 0)
                r["amount"] = sign * amt
                r["ref"] = ref or r["ref"]
                out.append(r)
                continue
            out.append(
                {
                    "iban": iban,
                    "date": bdate,
                    "amount": sign * amt,
                    "label": info,
                    "ref": ref,
                    "cp_iban": "",
                }
            )
    return accounts, out


def categorize(e, rules, own):
    low = e["label"].lower()
    if e["cp_iban"] and e["cp_iban"] in own:
        return ("transfer", "Entre mes comptes")
    for dest, kws in rules["transfers"].items():
        if any(k in low for k in kws):
            return ("transfer", dest)
    if e["amount"] > 0:
        if any(k in low for k in ["salaire", "salary", "lohn", "traitement"]):
            return ("income", "Salaire")
        if any(k in low for k in ["rembours", "remboursement", "retour", "refund"]):
            return ("income", "Remboursements")
        return ("income", "Autres revenus")
    for cat, kws in rules["categories"].items():
        if any(k in low for k in kws):
            return ("expense", cat)
    if "twint" in low and ("débit twint" in low or "debit twint" in low):
        return ("expense", "TWINT entre particuliers")
    if any(k in low for k in ["ordre permanent", "ordre e-banking", "mobile banking", "virement"]):
        return ("expense", "Virements à qualifier")
    return ("expense", "Non catégorisé")
