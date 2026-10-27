"""Fabrique de relevés camt.053 fictifs (ticket L1-03), .04 et .08, valides XSD.

Aucune donnée réelle : IBAN d'exemple officiel suisse, contreparties inventées. Les montants sont
des chaînes décimales positives (`"45.50"`), le sens est porté par `debit`.
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from hypothesis import strategies as st
from lxml import etree

IBAN = "CH9300762011623852957"  # IBAN d'exemple officiel suisse
IBAN_2 = "CH5604835012345678009"  # second compte fictif
OTHER_IBAN = "CH4431999123000889012"  # contrepartie fictive
NS = "urn:iso:std:iso:20022:tech:xsd:camt.053.001.{v}"


@dataclass
class Detail:
    amount: str | None
    debit: bool | None = None  # None : celui de la Ntry
    ref: str | None = None  # TxDtls/Refs/AcctSvcrRef
    counterparty: str | None = None
    label: str | None = None


@dataclass
class Tx:
    amount: str
    debit: bool
    booking: date
    value: date | None = None
    counterparty: str | None = "Boulangerie Fictive SA"
    counterparty_iban: str | None = None
    label: str | None = "Achat carte"
    remittance: list[str] = field(default_factory=list)
    qr_ref: str | None = None
    bank_ref: str | None = None  # Ntry/AcctSvcrRef
    detail_ref: str | None = None  # TxDtls/Refs/AcctSvcrRef (un seul détail)
    status: str = "BOOK"
    reversal: bool = False
    tx_code: tuple[str, str, str] = ("PMNT", "CCRD", "POSD")
    details: list[Detail] | None = None  # plusieurs TxDtls : écriture groupée
    no_details: bool = False  # Ntry sans NtryDtls
    fx: tuple[str, str, str, str] | None = None  # (montant, devise source, cible, cours)
    currency: str = "CHF"

    def signed(self) -> Decimal:
        value = Decimal(self.amount)
        value = -value if self.debit else value
        return -value if self.reversal else value


@dataclass
class Stmt:
    opening: Decimal
    opening_date: date
    entries: list[Tx]
    closing_date: date | None = None
    iban: str = IBAN
    currency: str = "CHF"
    closing: Decimal | None = None  # None : calculé (cohérent)
    stmt_id: str = "STMT-1"
    with_opening: bool = True

    def computed_closing(self) -> Decimal:
        booked = sum((t.signed() for t in self.entries if t.status == "BOOK"), Decimal(0))
        return self.opening + booked

    def end(self) -> date:
        if self.closing_date is not None:
            return self.closing_date
        dates = [t.booking for t in self.entries] or [self.opening_date]
        return max(dates)


def _amt(parent: etree._Element, tag: str, ns: str, amount: str, ccy: str) -> None:
    el = etree.SubElement(parent, f"{{{ns}}}{tag}", Ccy=ccy)
    el.text = f"{Decimal(amount):.2f}"


class _B:
    def __init__(self, version: str) -> None:
        self.v = version
        self.ns = NS.format(v=version)

    def el(self, parent: etree._Element, tag: str, text: str | None = None) -> etree._Element:
        e = etree.SubElement(parent, f"{{{self.ns}}}{tag}")
        if text is not None:
            e.text = text
        return e

    def path(self, parent: etree._Element, path: str, text: str) -> etree._Element:
        node = parent
        for part in path.split("/"):
            node = self.el(node, part)
        node.text = text
        return node

    def party(self, parent: etree._Element, role: str, name: str) -> None:
        p = self.el(parent, role)
        if self.v == "08":
            p = self.el(p, "Pty")
        self.el(p, "Nm", name)

    def balance(self, stmt: etree._Element, code: str, amount: Decimal, on: date, ccy: str) -> None:
        bal = self.el(stmt, "Bal")
        self.path(bal, "Tp/CdOrPrtry/Cd", code)
        _amt(bal, "Amt", self.ns, str(abs(amount)), ccy)
        self.el(bal, "CdtDbtInd", "DBIT" if amount < 0 else "CRDT")
        self.path(bal, "Dt/Dt", on.isoformat())

    def tx_details(self, dtls: etree._Element, t: Tx, d: Detail | None, debit: bool) -> None:
        tx = self.el(dtls, "TxDtls")
        ref = d.ref if d is not None else t.detail_ref
        if ref:
            self.path(tx, "Refs/AcctSvcrRef", ref)
        amount = d.amount if d is not None else t.amount
        if amount is not None:
            _amt(tx, "Amt", self.ns, amount, t.currency)
            d_debit = d.debit if d is not None and d.debit is not None else debit
            self.el(tx, "CdtDbtInd", "DBIT" if d_debit else "CRDT")
        elif self.v == "04":
            raise ValueError("TxDtls/Amt est obligatoire en .04")
        if t.fx is not None:
            instd = self.el(self.el(tx, "AmtDtls"), "InstdAmt")
            _amt(instd, "Amt", self.ns, t.fx[0], t.fx[1])
            xchg = self.el(instd, "CcyXchg")
            self.el(xchg, "SrcCcy", t.fx[1])
            self.el(xchg, "TrgtCcy", t.fx[2])
            self.el(xchg, "XchgRate", t.fx[3])
        name = d.counterparty if d is not None else t.counterparty
        if name or t.counterparty_iban:
            parties = self.el(tx, "RltdPties")
            role = "Cdtr" if t.debit else "Dbtr"
            if name:
                self.party(parties, role, name)
            if t.counterparty_iban and d is None:
                self.path(parties, f"{role}Acct/Id/IBAN", t.counterparty_iban)
        if d is None and (t.remittance or t.qr_ref):
            rmt = self.el(tx, "RmtInf")
            for line in t.remittance:
                self.el(rmt, "Ustrd", line)
            if t.qr_ref:
                self.path(rmt, "Strd/CdtrRefInf/Ref", t.qr_ref)
        label = d.label if d is not None else t.label
        if label:
            self.el(tx, "AddtlTxInf", label)

    def entry(self, stmt: etree._Element, t: Tx) -> None:
        n = self.el(stmt, "Ntry")
        _amt(n, "Amt", self.ns, t.amount, t.currency)
        self.el(n, "CdtDbtInd", "DBIT" if t.debit else "CRDT")
        if t.reversal:
            self.el(n, "RvslInd", "true")
        if self.v == "04":
            self.el(n, "Sts", t.status)
        else:
            self.path(n, "Sts/Cd", t.status)
        self.path(n, "BookgDt/Dt", t.booking.isoformat())
        self.path(n, "ValDt/Dt", (t.value or t.booking).isoformat())
        if t.bank_ref:
            self.el(n, "AcctSvcrRef", t.bank_ref)
        domn = self.el(self.el(n, "BkTxCd"), "Domn")
        self.el(domn, "Cd", t.tx_code[0])
        fmly = self.el(domn, "Fmly")
        self.el(fmly, "Cd", t.tx_code[1])
        self.el(fmly, "SubFmlyCd", t.tx_code[2])
        if not t.no_details:
            dtls = self.el(n, "NtryDtls")
            for d in t.details if t.details is not None else [None]:
                self.tx_details(dtls, t, d, t.debit)
        self.el(n, "AddtlNtryInf", "Ecriture fictive")

    def document(self, stmts: list[Stmt]) -> bytes:
        root = etree.Element(f"{{{self.ns}}}Document", nsmap={None: self.ns})
        msg = self.el(root, "BkToCstmrStmt")
        hdr = self.el(msg, "GrpHdr")
        self.el(hdr, "MsgId", "MSG-FICTIF-1")
        self.el(hdr, "CreDtTm", "2026-10-27T08:00:00")
        for s in stmts:
            stmt = self.el(msg, "Stmt")
            self.el(stmt, "Id", s.stmt_id)
            self.el(stmt, "CreDtTm", "2026-10-27T08:00:00")
            period = self.el(stmt, "FrToDt")
            self.el(period, "FrDtTm", f"{s.opening_date.isoformat()}T00:00:00")
            self.el(period, "ToDtTm", f"{s.end().isoformat()}T23:59:59")
            acct = self.el(stmt, "Acct")
            self.path(acct, "Id/IBAN", s.iban)
            self.el(acct, "Ccy", s.currency)
            if s.with_opening:
                self.balance(stmt, "OPBD", s.opening, s.opening_date, s.currency)
            closing = s.closing if s.closing is not None else s.computed_closing()
            self.balance(stmt, "CLBD", closing, s.end(), s.currency)
            for t in s.entries:
                self.entry(stmt, t)
        return bytes(etree.tostring(root, xml_declaration=True, encoding="UTF-8"))


def camt053(stmts: list[Stmt] | Stmt, version: str = "08") -> bytes:
    if isinstance(stmts, Stmt):
        stmts = [stmts]
    return _B(version).document(stmts)


def zipped(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


# --- Historique fictif et exports qui se chevauchent -----------------------------------------

NAMES = ["Boulangerie Fictive SA", "Epicerie du Coin", "Jean Exemple", "Assurance Imaginaire"]


@dataclass
class History:
    """Les écritures d'un compte jour par jour, d'où l'on tire des exports cohérents."""

    start: date
    opening: Decimal
    days: list[list[Tx]]
    iban: str = IBAN

    def balance_before(self, day: int) -> Decimal:
        total = self.opening
        for txs in self.days[:day]:
            total += sum((t.signed() for t in txs if t.status == "BOOK"), Decimal(0))
        return total

    def export(self, first: int, last: int, stmt_id: str = "STMT") -> Stmt:
        """Relevé des jours [first, last] inclus, journées complètes."""
        entries = [t for txs in self.days[first : last + 1] for t in txs]
        return Stmt(
            opening=self.balance_before(first),
            opening_date=self.start + timedelta(days=first),
            closing_date=self.start + timedelta(days=last),
            entries=entries,
            iban=self.iban,
            stmt_id=f"{stmt_id}-{first}-{last}",
        )

    def booked(self) -> int:
        return sum(1 for txs in self.days for t in txs if t.status == "BOOK")


amounts = st.integers(min_value=1, max_value=500_000).map(lambda c: f"{Decimal(c) / 100:.2f}")


@st.composite
def transactions(draw: st.DrawFn, booking: date) -> Tx:
    twin = draw(st.booleans())  # contreparties et libellés peu variés : collisions voulues
    return Tx(
        amount=draw(st.sampled_from(["20.00", "45.50"]) if twin else amounts),
        debit=draw(st.booleans()),
        booking=booking,
        counterparty=draw(st.sampled_from(NAMES)),
        label=draw(st.sampled_from(["TWINT", "Achat carte", "Virement"])),
        status=draw(st.sampled_from(["BOOK"] * 9 + ["PDNG"])),
        reversal=draw(st.sampled_from([False] * 9 + [True])),
    )


@st.composite
def histories(draw: st.DrawFn, max_days: int = 12) -> History:
    n = draw(st.integers(min_value=2, max_value=max_days))
    start = date(2026, 1, 1) + timedelta(days=draw(st.integers(0, 300)))
    days = [draw(st.lists(transactions(start + timedelta(days=i)), max_size=4)) for i in range(n)]
    opening = Decimal(draw(st.integers(min_value=0, max_value=1_000_000))) / 100
    return History(start=start, opening=opening, days=days)
