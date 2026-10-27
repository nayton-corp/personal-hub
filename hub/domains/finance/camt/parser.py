"""Parseur camt.053 (ticket L1-04) : lxml durci, version lue dans l'espace de noms, une seule
table de correspondance pour .04 et .08 (spécification, section 4)."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path
from typing import Literal

from lxml import etree
from lxml.etree import _Element

from hub.core import canonical
from hub.core.money import CurrencyError, Money
from hub.core.text import compact_iban
from hub.domains.finance.camt.models import (
    Anomaly,
    Balance,
    ParsedEntry,
    ParsedFile,
    ParsedStatement,
)

MAX_BYTES = 20 * 1024 * 1024
NS_PREFIX = "urn:iso:std:iso:20022:tech:xsd:camt.053.001."
VERSIONS: tuple[Literal["04", "08"], ...] = ("04", "08")
XSD_DIR = Path(__file__).parent / "xsd"


class CamtError(ValueError):
    """Fichier refusé ; `code` est un type d'erreur stable (`import.invalid_schema`)."""

    def __init__(self, reason: str, code: str = "import.invalid_schema") -> None:
        super().__init__(reason)
        self.code = code
        self.reason = reason


def _parser() -> etree.XMLParser:
    return etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        huge_tree=False,
        load_dtd=False,
        dtd_validation=False,
        remove_comments=True,
        remove_pis=True,
    )


@lru_cache(maxsize=len(VERSIONS))
def schema(version: str) -> etree.XMLSchema:
    doc = etree.parse(str(XSD_DIR / f"camt.053.001.{version}.xsd"), _parser())
    return etree.XMLSchema(doc)


def detect_version(root: _Element) -> Literal["04", "08"]:
    ns = etree.QName(root).namespace or ""
    if not ns.startswith(NS_PREFIX) or etree.QName(root).localname != "Document":
        raise CamtError("pas un relevé camt.053")
    suffix = ns.removeprefix(NS_PREFIX)
    for v in VERSIONS:
        if suffix == v:
            return v
    raise CamtError(f"version camt.053 non prise en charge : .001.{suffix[:4]}")


def load(data: bytes) -> tuple[_Element, Literal["04", "08"]]:
    """Analyse et valide contre le XSD ISO 20022 de la version détectée."""
    if len(data) > MAX_BYTES:
        raise CamtError("fichier trop volumineux (20 Mo au plus)")
    try:
        tree = etree.ElementTree(etree.fromstring(data, _parser()))
    except etree.XMLSyntaxError as exc:
        raise CamtError("XML mal formé") from exc
    if getattr(tree.docinfo, "doctype", ""):  # absent des stubs lxml
        raise CamtError("DOCTYPE refusé")
    root = tree.getroot()
    version = detect_version(root)
    xsd = schema(version)
    if not xsd.validate(tree):
        first = xsd.error_log.last_error  # type: ignore[attr-defined]
        line = first.line if first is not None else 0
        raise CamtError(f"non conforme au schéma camt.053.001.{version} (ligne {line})")
    return root, version


class _Reader:
    """Lecture par chemins relatifs (`RltdPties/Cdtr/Nm`), par dictionnaires d'enfants mis en
    cache : `find` répété coûte trop cher sur 10'000 écritures. `forget()` vide le cache."""

    def __init__(self, ns: str) -> None:
        self.ns = ns
        self._tags: dict[str, tuple[str, ...]] = {}
        self._kids: dict[_Element, dict[str, list[_Element]]] = {}

    def _split(self, path: str) -> tuple[str, ...]:
        found = self._tags.get(path)
        if found is None:
            found = self._tags[path] = tuple(f"{{{self.ns}}}{p}" for p in path.split("/"))
        return found

    def _children(self, node: _Element) -> dict[str, list[_Element]]:
        kids = self._kids.get(node)
        if kids is None:
            kids = {}
            for child in node:
                kids.setdefault(child.tag, []).append(child)
            self._kids[node] = kids
        return kids

    def forget(self) -> None:
        self._kids.clear()

    def all(self, el: _Element | None, path: str) -> list[_Element]:
        if el is None:
            return []
        level = [el]
        for tag in self._split(path):
            level = [c for node in level for c in self._children(node).get(tag, ())]
            if not level:
                return []
        return level

    def one(self, el: _Element | None, path: str) -> _Element | None:
        node = el
        for tag in self._split(path):
            if node is None:
                return None
            found = self._children(node).get(tag)
            node = found[0] if found else None
        return node

    def first(self, el: _Element | None, *paths: str) -> _Element | None:
        """Premier chemin trouvé (un élément lxml sans enfant est faux : pas de `or`)."""
        for path in paths:
            found = self.one(el, path)
            if found is not None:
                return found
        return None

    def text(self, el: _Element | None, *paths: str) -> str | None:
        """Premier chemin qui donne un texte non vide."""
        for path in paths:
            found = self.one(el, path)
            if found is not None and found.text and (value := found.text.strip()):
                return value
        return None

    def date(self, el: _Element | None, path: str) -> str | None:
        value = self.text(el, f"{path}/Dt", f"{path}/DtTm")
        return value[:10] if value else None


def _minor(amount: str, currency: str) -> int:
    try:
        Decimal(amount)
    except InvalidOperation:
        raise CamtError("montant illisible") from None
    return Money.from_decimal(amount, currency).minor


def _signed(minor: int, cdt_dbt: str | None) -> int:
    return -minor if cdt_dbt == "DBIT" else minor


class _StatementParser:
    def __init__(self, r: _Reader, version: str) -> None:
        self.r = r
        self.version = version

    def balance(self, stmt: _Element, codes: tuple[str, ...]) -> Balance | None:
        r = self.r
        for code in codes:
            for bal in r.all(stmt, "Bal"):
                if r.text(bal, "Tp/CdOrPrtry/Cd") != code:
                    continue
                amt = r.one(bal, "Amt")
                on = r.date(bal, "Dt")
                if amt is None or amt.text is None or on is None:
                    continue
                minor = _minor(amt.text, str(amt.get("Ccy")))
                return Balance(on_date=on, amount_minor=_signed(minor, r.text(bal, "CdtDbtInd")))
        return None

    def status(self, ntry: _Element) -> str | None:
        if self.version == "04":
            return self.r.text(ntry, "Sts")
        return self.r.text(ntry, "Sts/Cd", "Sts/Prtry")

    def tx_code(self, el: _Element | None) -> str | None:
        r = self.r
        domain = r.text(el, "BkTxCd/Domn/Cd")
        if domain:
            family = r.text(el, "BkTxCd/Domn/Fmly/Cd") or ""
            sub = r.text(el, "BkTxCd/Domn/Fmly/SubFmlyCd") or ""
            return f"{domain}/{family}/{sub}"
        return r.text(el, "BkTxCd/Prtry/Cd")

    def party(self, tx: _Element | None, debit: bool) -> tuple[str | None, str | None]:
        r = self.r
        role = "Cdtr" if debit else "Dbtr"
        name = r.text(
            tx,
            f"RltdPties/{role}/Nm",
            f"RltdPties/{role}/Pty/Nm",
            f"RltdPties/Ultmt{role}/Nm",
            f"RltdPties/Ultmt{role}/Pty/Nm",
        )
        iban = r.text(tx, f"RltdPties/{role}Acct/Id/IBAN")
        return name, compact_iban(iban) if iban else None

    def remittance(self, tx: _Element | None) -> str:
        r = self.r
        parts = [e.text.strip() for e in r.all(tx, "RmtInf/Ustrd") if e.text and e.text.strip()]
        parts += [
            e.text.strip()
            for e in r.all(tx, "RmtInf/Strd/CdtrRefInf/Ref")
            if e.text and e.text.strip()
        ]
        return " ".join(parts)

    def fx(self, tx: _Element | None) -> str | None:
        r = self.r
        instd = r.one(tx, "AmtDtls/InstdAmt/Amt")
        xchg = r.first(tx, "AmtDtls/InstdAmt/CcyXchg", "AmtDtls/TxAmt/CcyXchg")
        if instd is None and xchg is None:
            return None
        out: dict[str, str] = {}
        if instd is not None and instd.text:
            out["instructed_amount"] = instd.text.strip()
            out["instructed_currency"] = str(instd.get("Ccy"))
        if xchg is not None:
            for key, path in (("source", "SrcCcy"), ("target", "TrgtCcy"), ("rate", "XchgRate")):
                value = r.text(xchg, path)
                if value:
                    out[key] = value
        return canonical.dumps(out)

    def detail_amount(self, tx: _Element, fallback_ind: str | None) -> tuple[int, str] | None:
        r = self.r
        amt = r.first(tx, "Amt", "AmtDtls/TxAmt/Amt")
        if amt is None or amt.text is None:
            return None
        ccy = str(amt.get("Ccy"))
        ind = r.text(tx, "CdtDbtInd") or fallback_ind
        return _signed(_minor(amt.text, ccy), ind), ccy

    def entries(self, ntry: _Element, index: int, anomalies: list[Anomaly]) -> list[ParsedEntry]:
        r = self.r
        amt = r.one(ntry, "Amt")
        if amt is None or amt.text is None:
            raise CamtError("écriture sans montant")
        currency = str(amt.get("Ccy"))
        cdt_dbt = r.text(ntry, "CdtDbtInd")
        signed = _signed(_minor(amt.text, currency), cdt_dbt)
        reversal = (r.text(ntry, "RvslInd") or "").lower() == "true"
        booking = r.date(ntry, "BookgDt") or r.date(ntry, "ValDt")
        if booking is None:
            raise CamtError("écriture sans date")
        value_date = r.date(ntry, "ValDt")
        debit = cdt_dbt == "DBIT"
        details = r.all(ntry, "NtryDtls/TxDtls")
        factor = -1 if reversal else 1

        def build(tx: _Element | None, amount: int, detail_index: int | None) -> ParsedEntry:
            name, iban = self.party(tx, debit)
            detail_ref = r.text(tx, "Refs/AcctSvcrRef")
            return ParsedEntry(
                ntry_index=index,
                detail_index=detail_index,
                booking_date=booking,
                value_date=value_date,
                amount_minor=amount * factor,
                currency=currency,
                reversal=reversal,
                counterparty=name,
                counterparty_iban=iban,
                label=r.text(tx, "AddtlTxInf") or r.text(ntry, "AddtlNtryInf") or "",
                remittance=self.remittance(tx),
                bank_ref=detail_ref or r.text(ntry, "AcctSvcrRef"),
                detail_ref=detail_ref,
                bank_tx_code=self.tx_code(tx) or self.tx_code(ntry),
                fx_json=self.fx(tx) or self.fx(ntry),
            )

        if len(details) <= 1:
            return [build(details[0] if details else None, signed, None)]
        amounts = [self.detail_amount(tx, cdt_dbt) for tx in details]
        if (
            all(a is not None and a[1] == currency for a in amounts)
            and sum(a[0] for a in amounts if a is not None) == signed
        ):
            return [
                build(tx, a[0], i)
                for i, (tx, a) in enumerate(zip(details, amounts, strict=True))
                if a is not None
            ]
        anomalies.append("grouped_not_split")
        return [build(None, signed, None)]

    def statement(self, stmt: _Element, index: int) -> ParsedStatement:
        r = self.r
        anomalies: list[Anomaly] = []
        iban = r.text(stmt, "Acct/Id/IBAN")
        currency = r.text(stmt, "Acct/Ccy")
        entries: list[ParsedEntry] = []
        ignored = 0
        opening = closing = None
        try:
            opening = self.balance(stmt, ("OPBD", "PRCD"))
            closing = self.balance(stmt, ("CLBD",))
            for i, ntry in enumerate(r.all(stmt, "Ntry")):
                if self.status(ntry) != "BOOK":
                    ignored += 1
                    continue
                entries.extend(self.entries(ntry, i, anomalies))
                r.forget()  # garde la mémoire bornée sur les gros relevés
        except CurrencyError:
            anomalies.append("unknown_currency")
            entries = []
        if opening is None or closing is None:
            anomalies.append("missing_balance")
        if currency is None and entries:
            currency = entries[0].currency
        return ParsedStatement(
            index=index,
            iban=compact_iban(iban) if iban else None,
            currency=currency,
            opening=opening,
            closing=closing,
            entries=entries,
            anomalies=sorted(set(anomalies)),
            ignored_pending=ignored,
        )


def parse(data: bytes) -> ParsedFile:
    root, version = load(data)
    r = _Reader(etree.QName(root).namespace or "")
    sp = _StatementParser(r, version)
    path = f"{{{r.ns}}}BkToCstmrStmt/{{{r.ns}}}Stmt"
    statements = []
    for i, stmt in enumerate(root.iterfind(path)):
        statements.append(sp.statement(stmt, i))
        r.forget()
    return ParsedFile(version=version, statements=statements)
