"""L1-03, L1-04, L1-05 : fabrique valide XSD, parseur durci, clé de dédoublonnage."""

import time
from datetime import date, timedelta
from decimal import Decimal

import pytest
from hypothesis import given, settings
from lxml import etree

from hub.domains.finance.registre.model import dedup
from hub.domains.finance.registre.model.statements import ParsedEntry
from hub.domains.finance.sources.infra import camt as parser
from tests.factories.camt import (
    IBAN,
    OTHER_IBAN,
    Detail,
    History,
    Stmt,
    Tx,
    camt053,
    histories,
)

D = date(2026, 10, 1)
VERSIONS = ["04", "08"]


def one(tx: Tx, version: str = "08", **kw: object) -> parser.ParsedStatement:
    stmt = Stmt(opening=Decimal("100.00"), opening_date=D, entries=[tx], **kw)  # type: ignore[arg-type]
    (s,) = parser.parse(camt053(stmt, version)).statements
    return s


@pytest.mark.parametrize("version", VERSIONS)
@given(h=histories())
@settings(max_examples=25, deadline=None)
def test_generated_files_pass_official_xsd(version: str, h: History) -> None:
    data = camt053(h.export(0, len(h.days) - 1), version)
    root = etree.fromstring(data)
    assert parser.schema(version).validate(etree.ElementTree(root))
    assert parser.parse(data).version == version


@pytest.mark.parametrize("version", VERSIONS)
def test_field_mapping(version: str) -> None:
    s = one(
        Tx(
            "45.50",
            True,
            D,
            value=D + timedelta(days=1),
            counterparty="Boulangerie Fictive SA",
            counterparty_iban=OTHER_IBAN,
            label="Achat carte",
            remittance=["Facture 12", "merci"],
            qr_ref="210000000003139471430009017",
            bank_ref="NTRY-1",
            detail_ref="TX-1",
            tx_code=("PMNT", "ICDT", "ESCT"),
        ),
        version,
    )
    assert s.iban == IBAN
    assert s.currency == "CHF"
    assert s.opening is not None
    assert s.opening.amount_minor == 10000
    assert s.closing is not None
    assert s.closing.amount_minor == 5450
    (e,) = s.entries
    assert e.amount_minor == -4550
    assert e.booking_date == "2026-10-01"
    assert e.value_date == "2026-10-02"
    assert e.counterparty == "Boulangerie Fictive SA"
    assert e.counterparty_iban == OTHER_IBAN
    assert e.label == "Achat carte"
    assert e.remittance == "Facture 12 merci 210000000003139471430009017"
    assert (e.bank_ref, e.detail_ref) == ("TX-1", "TX-1")
    assert e.bank_tx_code == "PMNT/ICDT/ESCT"
    assert s.anomalies == []


@pytest.mark.parametrize("version", VERSIONS)
def test_credit_uses_debtor_and_ntry_fallbacks(version: str) -> None:
    (e,) = one(
        Tx("10.00", False, D, counterparty="Employeur Fictif", label=None, bank_ref="N-9"),
        version,
    ).entries
    assert e.amount_minor == 1000
    assert e.counterparty == "Employeur Fictif"
    assert e.label == "Ecriture fictive"  # AddtlNtryInf en repli
    assert (e.bank_ref, e.detail_ref) == ("N-9", None)


@pytest.mark.parametrize("version", VERSIONS)
def test_reversal_inverts_sign(version: str) -> None:
    (e,) = one(Tx("12.00", True, D, reversal=True), version).entries
    assert e.amount_minor == 1200
    assert e.reversal


@pytest.mark.parametrize("version", VERSIONS)
def test_pending_entries_are_ignored(version: str) -> None:
    s = one(Tx("12.00", True, D, status="PDNG"), version)
    assert s.entries == []
    assert s.ignored_pending == 1


@pytest.mark.parametrize("version", VERSIONS)
def test_fx_kept_as_is(version: str) -> None:
    (e,) = one(Tx("30.00", True, D, fx=("31.00", "EUR", "CHF", "0.9677")), version).entries
    assert e.fx_json == (
        '{"instructed_amount":"31.00","instructed_currency":"EUR","rate":"0.9677",'
        '"source":"EUR","target":"CHF"}'
    )


@pytest.mark.parametrize("version", VERSIONS)
def test_grouped_entry_split_when_details_sum(version: str) -> None:
    s = one(
        Tx("50.00", True, D, details=[Detail("20.00", ref="A"), Detail("30.00", ref="B")]),
        version,
    )
    assert [(e.amount_minor, e.detail_ref, e.detail_index) for e in s.entries] == [
        (-2000, "A", 0),
        (-3000, "B", 1),
    ]
    assert s.anomalies == []


@pytest.mark.parametrize("version", VERSIONS)
def test_grouped_entry_not_split_when_sum_differs(version: str) -> None:
    s = one(Tx("50.00", True, D, details=[Detail("20.00"), Detail("31.00")]), version)
    assert [e.amount_minor for e in s.entries] == [-5000]
    assert s.anomalies == ["grouped_not_split"]


def test_grouped_entry_without_detail_amounts_08() -> None:
    s = one(Tx("50.00", True, D, details=[Detail(None), Detail(None)]), "08")
    assert s.anomalies == ["grouped_not_split"]


@pytest.mark.parametrize("version", VERSIONS)
def test_entry_without_details(version: str) -> None:
    (e,) = one(Tx("7.00", True, D, no_details=True), version).entries
    assert (e.amount_minor, e.counterparty, e.bank_tx_code) == (-700, None, "PMNT/CCRD/POSD")


def test_missing_opening_and_unknown_currency() -> None:
    s = one(Tx("1.00", True, D), with_opening=False)
    assert s.anomalies == ["missing_balance"]
    data = camt053(Stmt(Decimal(0), D, [Tx("1.00", True, D, currency="XAU")], currency="XAU"))
    (s,) = parser.parse(data).statements
    assert "unknown_currency" in s.anomalies
    assert s.entries == []


def test_xsd_invalid_is_refused() -> None:
    data = camt053(Stmt(Decimal(1), D, [Tx("1.00", True, D)])).replace(b"<Sts><Cd>", b"<Sts><X>")
    data = data.replace(b"</Cd></Sts>", b"</X></Sts>")
    with pytest.raises(parser.CamtError, match="non conforme"):
        parser.parse(data)
    with pytest.raises(parser.CamtError, match="mal formé"):
        parser.parse(b"<Document")
    with pytest.raises(parser.CamtError, match="pas un relevé"):
        parser.parse(b"<a/>")
    other = camt053(Stmt(Decimal(1), D, [])).replace(b"camt.053.001.08", b"camt.053.001.02")
    with pytest.raises(parser.CamtError, match="non prise en charge"):
        parser.parse(other)
    with pytest.raises(parser.CamtError, match="volumineux"):
        parser.parse(b" " * (parser.MAX_BYTES + 1))


def test_doctype_and_external_entities_are_refused(tmp_path: object) -> None:
    body = camt053(Stmt(Decimal(1), D, [Tx("1.00", True, D, label="X")]))
    head, rest = body.split(b"?>", 1)
    xxe = (
        head
        + b'?><!DOCTYPE Document [<!ENTITY x SYSTEM "file:///etc/passwd">]>'
        + rest.replace(b">X<", b">&x;<")
    )
    with pytest.raises(parser.CamtError) as exc:
        parser.parse(xxe)
    assert exc.value.code == "import.invalid_schema"
    bomb = head + b'?><!DOCTYPE Document [<!ENTITY a "aaaa">]>' + rest
    with pytest.raises(parser.CamtError, match="DOCTYPE"):
        parser.parse(bomb)


def _coverage_running() -> bool:
    try:
        import coverage
    except ImportError:  # pragma: no cover
        return False
    return coverage.Coverage.current() is not None


def test_five_megabytes_parse_quickly() -> None:
    day = [Tx("20.00", True, D + timedelta(days=i % 28)) for i in range(10500)]
    data = camt053(Stmt(Decimal(1_000_000), D, day))
    assert len(data) > 5 * 1024 * 1024
    start = time.perf_counter()
    (s,) = parser.parse(data).statements
    elapsed = time.perf_counter() - start
    assert len(s.entries) == 10500
    # objectif : moins de 2 s sur le Pi 5 ; la mesure de couverture ralentit environ 4 fois
    assert elapsed < (8.0 if _coverage_running() else 2.0)


# --- dédoublonnage ------------------------------------------------------------------------


def _e(**kw: object) -> ParsedEntry:
    base: dict[str, object] = {
        "ntry_index": 0,
        "detail_index": None,
        "booking_date": "2026-10-01",
        "value_date": None,
        "amount_minor": -2000,
        "currency": "CHF",
        "reversal": False,
        "counterparty": "Jean Exemple",
        "counterparty_iban": None,
        "label": "TWINT",
        "remittance": "",
        "bank_ref": None,
        "detail_ref": None,
        "bank_tx_code": None,
        "fx_json": None,
    }
    return ParsedEntry(**{**base, **kw})  # type: ignore[arg-type]


def test_two_identical_twint_same_day_get_distinct_keys() -> None:
    k = dedup.keys(IBAN, [_e(), _e()])
    assert len(set(k)) == 2
    assert dedup.keys(IBAN, [_e(), _e()]) == k  # stable


def test_detail_reference_ignores_label() -> None:
    a = dedup.keys(IBAN, [_e(detail_ref="R1", label="Libellé .04")])
    b = dedup.keys(IBAN, [_e(detail_ref="R1", label="libelle .08 différent")])
    assert a == b
    assert dedup.keys(IBAN, [_e(label="A")]) != dedup.keys(IBAN, [_e(label="B")])
    # la référence banque seule ne fusionne plus deux écritures différentes
    assert dedup.keys(IBAN, [_e(bank_ref="X", amount_minor=1)]) != dedup.keys(
        IBAN, [_e(bank_ref="X", amount_minor=2)]
    )


def test_keys_are_versioned_and_opening_is_unique() -> None:
    assert dedup.opening_key("acc") == dedup.opening_key("acc")
    assert dedup.opening_key("acc") != dedup.opening_key("other")
