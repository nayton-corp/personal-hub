"""Données fictives d'une instance (chantier S13) : un an de relevés camt.053 pour deux comptes.

    python3 scripts/demo_data.py <dossier> [--today AAAA-MM-JJ]

Bibliothèque standard seulement : le script tourne aussi bien dans le venv que dans l'image du
hub (instance d'essai). Il écrit un relevé par compte et par mois, de douze mois avant `today`
jusqu'à la veille, et `accounts.tsv` (IBAN, nom, options de `accounts add`) pour créer les comptes
avant `hub finance import-history <dossier>`. Le même jour donne les mêmes fichiers.
Personnes, employeur et gérance sont inventés ; les commerces sont des enseignes courantes pour
que les packs de règles les classent.
"""

import datetime as dt
import random
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

NS = "urn:iso:std:iso:20022:tech:xsd:camt.053.001.08"


def iban(bban: str) -> str:
    """IBAN suisse valide (contrôle mod 97) pour un BBAN fictif de 17 chiffres."""
    digits = "".join(str(int(c, 36)) for c in bban + "CH00")
    return f"CH{98 - int(digits) % 97:02d}{bban}"


CURRENT = iban("00762011623852957")  # le compte des fabriques de test
SAVINGS = iban("00762011623859999")
# options de `hub finance accounts add` : le courant suit le budget, les deux sont des liquidités
ACCOUNTS = [
    (CURRENT, "Compte courant fictif", "--budget --liquid"),
    (SAVINGS, "Épargne fictive", "--liquid"),
]


@dataclass(frozen=True)
class Tx:
    day: dt.date
    cents: int  # signé : négatif au débit
    name: str
    label: str
    code: tuple[str, str, str]
    counter_iban: str | None = None


CARD = ("PMNT", "CCRD", "POSD")
OUT = ("PMNT", "ICDT", "DMCT")
IN = ("PMNT", "RCDT", "ESCT")
SHOPS = [("Migros", 2_000, 14_000), ("Coop", 1_500, 11_000), ("Denner", 800, 4_500)]
OUTINGS = [("Restaurant du Lac", 3_500, 12_000), ("Café de la Gare", 600, 2_400)]


def _month_days(first: dt.date, last: dt.date) -> list[dt.date]:
    return [first + dt.timedelta(days=i) for i in range((last - first).days + 1)]


def transactions(start: dt.date, end: dt.date) -> dict[str, list[Tx]]:
    rnd = random.Random(start.toordinal())  # noqa: S311 (données fictives, pas de sécurité)
    cur: list[Tx] = []
    sav: list[Tx] = []
    for day in _month_days(start, end):
        if day.day == 25:
            cur.append(
                Tx(day, 620_000, "Employeur Fictif SA", "Salaire", IN, iban("00762099900000001"))
            )
        if day.day == 1:
            cur.append(
                Tx(day, -185_000, "Gérance Imaginaire SA", "Loyer", OUT, iban("00762099900000002"))
            )
            cur.append(Tx(day, -42_050, "Assurance Imaginaire", "Prime maladie", OUT))
        if day.day == 5:
            cur.append(Tx(day, -6_490, "Swisscom", "Abonnement mobile", OUT))
            cur.append(Tx(day, -1_890, "Netflix", "Abonnement", CARD))
        if day.day == 27:
            cur.append(Tx(day, -50_000, "Épargne fictive", "Virement épargne", OUT, SAVINGS))
            sav.append(Tx(day, 50_000, "Compte courant fictif", "Virement épargne", IN, CURRENT))
        if day.weekday() in (1, 4, 5):
            name, low, high = rnd.choice(SHOPS)
            cur.append(Tx(day, -rnd.randint(low, high), name, "Achat carte", CARD))
        if day.weekday() == 5 and rnd.random() < 0.6:
            name, low, high = rnd.choice(OUTINGS)
            cur.append(Tx(day, -rnd.randint(low, high), name, "Achat carte", CARD))
        if day.weekday() == 0 and rnd.random() < 0.5:
            cur.append(Tx(day, -rnd.randint(450, 9_000), "CFF", "Billet de train", CARD))
    return {CURRENT: cur, SAVINGS: sav}


def _el(parent: ET.Element, path: str, text: str | None = None, **attrs: str) -> ET.Element:
    node = parent
    for part in path.split("/"):
        node = ET.SubElement(node, f"{{{NS}}}{part}")
    node.attrib.update(attrs)
    if text is not None:
        node.text = text
    return node


def _amount(parent: ET.Element, tag: str, cents: int) -> None:
    _el(parent, tag, f"{Decimal(abs(cents)) / 100:.2f}", Ccy="CHF")


def _balance(stmt: ET.Element, code: str, cents: int, on: dt.date) -> None:
    bal = _el(stmt, "Bal")
    _el(bal, "Tp/CdOrPrtry/Cd", code)
    _amount(bal, "Amt", cents)
    _el(bal, "CdtDbtInd", "DBIT" if cents < 0 else "CRDT")
    _el(bal, "Dt/Dt", on.isoformat())


def _entry(stmt: ET.Element, t: Tx, ref: str) -> None:
    n = _el(stmt, "Ntry")
    _amount(n, "Amt", t.cents)
    debit = t.cents < 0
    _el(n, "CdtDbtInd", "DBIT" if debit else "CRDT")
    _el(n, "Sts/Cd", "BOOK")
    _el(n, "BookgDt/Dt", t.day.isoformat())
    _el(n, "ValDt/Dt", t.day.isoformat())
    _el(n, "AcctSvcrRef", ref)
    domn = _el(n, "BkTxCd/Domn")
    _el(domn, "Cd", t.code[0])
    _el(domn, "Fmly/Cd", t.code[1])
    _el(domn.find(f"{{{NS}}}Fmly"), "SubFmlyCd", t.code[2])  # type: ignore[arg-type]
    tx = _el(n, "NtryDtls/TxDtls")
    _el(tx, "Refs/AcctSvcrRef", ref)
    _amount(tx, "Amt", t.cents)
    _el(tx, "CdtDbtInd", "DBIT" if debit else "CRDT")
    role = "Cdtr" if debit else "Dbtr"
    parties = _el(tx, "RltdPties")
    _el(parties, f"{role}/Pty/Nm", t.name)
    if t.counter_iban:
        _el(parties, f"{role}Acct/Id/IBAN", t.counter_iban)
    _el(tx, "RmtInf/Ustrd", t.label)
    _el(tx, "AddtlTxInf", t.label)


def statement(account: str, first: dt.date, last: dt.date, opening: int, txs: list[Tx]) -> bytes:
    ET.register_namespace("", NS)
    root = ET.Element(f"{{{NS}}}Document")
    msg = _el(root, "BkToCstmrStmt")
    created = f"{(last + dt.timedelta(days=1)).isoformat()}T06:00:00"
    _el(msg, "GrpHdr/MsgId", f"DEMO-{account[-4:]}-{first:%Y%m}")
    _el(msg.find(f"{{{NS}}}GrpHdr"), "CreDtTm", created)  # type: ignore[arg-type]
    stmt = _el(msg, "Stmt")
    _el(stmt, "Id", f"DEMO-{account[-4:]}-{first:%Y%m}")
    _el(stmt, "CreDtTm", created)
    _el(stmt, "FrToDt/FrDtTm", f"{first.isoformat()}T00:00:00")
    _el(stmt.find(f"{{{NS}}}FrToDt"), "ToDtTm", f"{last.isoformat()}T23:59:59")  # type: ignore[arg-type]
    _el(stmt, "Acct/Id/IBAN", account)
    _el(stmt.find(f"{{{NS}}}Acct"), "Ccy", "CHF")  # type: ignore[arg-type]
    _balance(stmt, "OPBD", opening, first)
    _balance(stmt, "CLBD", opening + sum(t.cents for t in txs), last)
    for i, t in enumerate(txs):
        _entry(stmt, t, f"DEMO-{account[-4:]}-{t.day:%Y%m%d}-{i:03d}")
    return bytes(ET.tostring(root, xml_declaration=True, encoding="UTF-8"))


def write(folder: Path, today: dt.date) -> list[Path]:
    """Écrit les relevés et accounts.tsv ; rend les fichiers écrits."""
    end = today - dt.timedelta(days=1)
    start = (end.replace(day=1) - dt.timedelta(days=335)).replace(day=1)
    folder.mkdir(parents=True, exist_ok=True)
    balances = {CURRENT: 850_000, SAVINGS: 2_400_000}
    written: list[Path] = []
    for account, txs in transactions(start, end).items():
        first = start
        while first <= end:
            nxt = (first.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
            last = min(nxt - dt.timedelta(days=1), end)
            month = [t for t in txs if first <= t.day <= last]
            path = folder / f"{account}-{first:%Y-%m}.xml"
            path.write_bytes(statement(account, first, last, balances[account], month))
            balances[account] += sum(t.cents for t in month)
            written.append(path)
            first = nxt
    lines = [f"{a}\t{name}\t{options}" for a, name, options in ACCOUNTS]
    (folder / "accounts.tsv").write_text("\n".join(lines) + "\n")
    return written


def main(argv: list[str]) -> int:
    if len(argv) not in (1, 3) or (len(argv) == 3 and argv[1] != "--today"):
        print(__doc__, file=sys.stderr)
        return 2
    today = dt.date.fromisoformat(argv[2]) if len(argv) == 3 else dt.date.today()  # noqa: DTZ011
    files = write(Path(argv[0]), today)
    print(f"{len(files)} relevés fictifs dans {argv[0]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
