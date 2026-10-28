"""Import Revolut (lot 5) : fichiers du collecteur Enable Banking et CSV de secours, rapprochés
et dédoublonnés comme des relevés camt.053. Données inventées seulement."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
import typer
from typer.testing import CliRunner

from hub.core.coredb import CoreDB
from hub.domains.finance import importer, revolut
from hub.domains.finance.domain import FinanceDomain
from tests.finance.conftest import rows

ACCOUNT = {
    "account_id": {"iban": "LT601010012345678901"},
    "currency": "CHF",
    "cash_account_type": "CACC",
    "product": "Current",
    "identification_hash": "hash-chf-0001",
}


def tx(ref: str, amount: str, cdi: str, on: str, status: str = "BOOK", **kw: Any) -> dict[str, Any]:
    return {
        "entry_reference": ref,
        "transaction_amount": {"currency": "CHF", "amount": amount},
        "credit_debit_indicator": cdi,
        "status": status,
        "booking_date": on,
        "value_date": on,
        "creditor": {"name": "Commerce Fictif"},
        "debtor": {"name": "Employeur Fictif SA"},
        "remittance_information": ["Achat fictif", "ref 42"],
        "bank_transaction_code": {"code": "CARD", "sub_code": "POS"},
        **kw,
    }


def eb_file(
    txs: list[dict[str, Any]],
    balance: str | None = "187.50",
    kind: str = "ITBD",
    on: str = "2026-10-21",
    account: dict[str, Any] | None = None,
    full: bool = False,
) -> bytes:
    balances = (
        [
            {
                "balance_type": kind,
                "balance_amount": {"currency": "CHF", "amount": balance},
                "reference_date": on,
            }
        ]
        if balance is not None
        else []
    )
    return json.dumps(
        {
            "format": "hub.revolut.v1",
            "source": "enable_banking",
            "fetched_at": "2026-10-21T18:00:00.000Z",
            "date_from": "2015-01-01" if full else "2026-10-11",
            "date_to": on,
            "full_history": full,
            "account": account or ACCOUNT,
            "balances": balances,
            "transactions": txs,
        }
    ).encode()


FIRST = [
    tx("r1", "12.50", "DBIT", "2026-10-20"),
    tx("r2", "100.00", "CRDT", "2026-10-21"),
    tx("p1", "3.00", "DBIT", "2026-10-21", status="PDNG"),
]

CSV = (
    "Type,Product,Started Date,Completed Date,Description,Amount,Fee,Currency,State,Balance\n"
    "CARD_PAYMENT,Current,2026-10-25 10:00:00,2026-10-25 10:01:00,Boulangerie Fictive,-4.00,0.00,CHF,COMPLETED,183.50\n"
    "TOPUP,Current,2026-10-26 09:00:00,2026-10-26 09:00:05,Recharge fictive,50.00,0.00,CHF,COMPLETED,233.50\n"
    "CARD_PAYMENT,Current,2026-10-26 12:00:00,2026-10-26 12:00:01,Café fictif,-3.00,0.10,CHF,COMPLETED,230.40\n"
    "CARD_PAYMENT,Current,2026-10-27 08:00:00,,En attente fictive,-9.00,0.00,CHF,PENDING,\n"
    "CARD_PAYMENT,Current,2026-10-27 08:00:00,2026-10-27 08:10:00,Refusé fictif,-1.00,0.00,CHF,DECLINED,\n"
    "TRANSFER,Savings,2026-10-26 09:00:00,2026-10-26 09:00:05,Vers coffre,10.00,0.00,EUR,COMPLETED,10.00\n"
).encode()


# --- parseurs ---------------------------------------------------------------------------------


def test_parse_eb() -> None:
    pf = revolut.parse_eb(eb_file(FIRST))
    (st,) = pf.statements
    assert st.account_ref == "revolut:CHF"
    assert st.iban is None
    assert st.ignored_pending == 1
    assert [e.amount_minor for e in st.entries] == [-1250, 10000]
    assert st.entries[0].counterparty == "Commerce Fictif"
    assert st.entries[1].counterparty == "Employeur Fictif SA"
    assert st.entries[0].detail_ref == "r1"
    assert st.entries[0].bank_tx_code == "CARD/POS"
    assert st.closing is not None
    assert st.closing.amount_minor == 18750
    assert st.opening is None
    # solde annoncé moins les écritures, la veille de la première
    assert st.derived_opening is not None
    assert (st.derived_opening.on_date, st.derived_opening.amount_minor) == ("2026-10-19", 10000)


def test_available_balance_is_never_a_checkpoint() -> None:
    (st,) = revolut.parse_eb(eb_file(FIRST, kind="ITAV")).statements
    assert st.closing is None
    assert st.derived_opening is not None  # sert quand même à ouvrir le compte


def test_pocket_ref_and_unknown_currency() -> None:
    pocket = {**ACCOUNT, "cash_account_type": "SVGS", "product": "Coffre Vacances"}
    suffix = hashlib.sha256(b"hash-chf-0001").hexdigest()[:6]
    assert revolut.parse_eb(eb_file([], account=pocket)).statements[0].account_ref == (
        f"revolut:CHF:coffre-vacances-{suffix}"
    )
    exotic = {**ACCOUNT, "currency": "HUF"}
    raw = [
        tx(
            "h1",
            "1000",
            "DBIT",
            "2026-10-20",
            transaction_amount={"currency": "HUF", "amount": "1000"},
        )
    ]
    (st,) = revolut.parse_eb(eb_file(raw, balance=None, account=exotic)).statements
    assert st.anomalies == ["unknown_currency"]


@pytest.mark.parametrize(
    "data",
    [
        b"{",
        b'{"format": "autre"}',
        json.dumps({"format": "hub.revolut.v1", "account": {}}).encode(),
    ],
)
def test_parse_eb_refuses(data: bytes) -> None:
    with pytest.raises(revolut.RevolutError):
        revolut.parse_eb(data)


def test_parse_csv() -> None:
    pf = revolut.parse_csv(CSV)
    chf, eur = pf.statements
    assert chf.account_ref == "revolut:CHF"
    assert eur.account_ref == "revolut:EUR:savings"
    assert [e.amount_minor for e in chf.entries] == [-400, 5000, -310]  # frais déduits
    assert chf.ignored_pending == 1
    assert chf.entries[0].bank_tx_code == "REVOLUT/CARD_PAYMENT"
    assert chf.closing is not None
    assert (chf.closing.on_date, chf.closing.amount_minor) == (
        "2026-10-26",
        23040,
    )
    assert chf.derived_opening is not None
    assert chf.derived_opening.amount_minor == 18750
    assert chf.anomalies == []
    broken = CSV.replace(b"233.50", b"234.50")
    assert revolut.parse_csv(broken).statements[0].anomalies == ["internal_check_failed"]


def test_detection() -> None:
    assert revolut.source_of(eb_file([])) == revolut.EB_SOURCE
    assert revolut.source_of(b"\xef\xbb\xbf" + CSV) == revolut.CSV_SOURCE
    assert revolut.source_of(b"Date,Montant\n") is None
    with pytest.raises(revolut.RevolutError):
        revolut.parse_csv(b"Date,Montant\n1,2\n")


# --- import -----------------------------------------------------------------------------------


@pytest.fixture
def app(finance: FinanceDomain) -> typer.Typer:
    core = CoreDB.from_settings(finance.settings)
    core.migrate()
    core.dispose()
    sub = finance.cli()
    assert sub is not None
    return sub


def run(app: typer.Typer, *args: str) -> tuple[int, str]:
    result = CliRunner().invoke(app, list(args))
    return result.exit_code, result.stdout


def drop(finance: FinanceDomain, name: str, data: bytes) -> importer.BatchReport:
    inbox: Path = finance.settings.paths.inbox
    inbox.mkdir(parents=True, exist_ok=True)
    path = inbox / name
    path.write_bytes(data)
    import os

    os.utime(path, (1, 1))  # plus de délai de copie
    return finance.importer.process_inbox()


def test_unknown_account_waits_then_add_account_opens_and_applies(
    finance: FinanceDomain, app: typer.Typer
) -> None:
    report = drop(finance, "revolut-a.json", eb_file(FIRST, full=True))
    assert report.counters()["needs_review"] == 1
    code, out = run(app, "revolut", "pending")
    assert code == 0, out
    (pending,) = json.loads(out)
    assert pending == {
        "ref": "revolut:CHF",
        "account_exists": False,
        "imports": 1,
        "entries": 2,
        "from": "2026-10-20",
        "to": "2026-10-21",
        "can_open": True,
    }
    assert "12.50" not in out
    assert "1250" not in out
    code, out = run(app, "revolut", "add-account", "revolut:CHF", "--name", "Revolut CHF")
    assert code == 0, out
    assert json.loads(out.splitlines()[-1])["opened"] is True
    balance = rows(finance, "SELECT sum(amount_minor) FROM entries")[0][0]
    assert balance == 18750
    assert rows(finance, "SELECT kind, on_date FROM checkpoints") == [("CLBD", "2026-10-21")]
    assert rows(finance, "SELECT status FROM imports") == [("applied",)]
    assert run(app, "revolut", "add-account", "revolut:XX", "--name", "x")[0] == 1


def _opened(finance: FinanceDomain, app: typer.Typer) -> None:
    drop(finance, "revolut-a.json", eb_file(FIRST, full=True))
    code, out = run(app, "revolut", "add-account", "revolut:CHF", "--name", "Revolut CHF")
    assert code == 0, out


def test_overlapping_sync_is_deduplicated(finance: FinanceDomain, app: typer.Typer) -> None:
    _opened(finance, app)
    later = [*FIRST[:2], tx("r3", "4.00", "DBIT", "2026-10-25")]
    report = drop(finance, "revolut-b.json", eb_file(later, balance="183.50", on="2026-10-25"))
    c = report.counters()
    assert (c["applied"], c["new_entries"], c["duplicate_entries"]) == (1, 1, 2)


def test_balance_gap_needs_review(finance: FinanceDomain, app: typer.Typer) -> None:
    _opened(finance, app)
    later = [tx("r3", "4.00", "DBIT", "2026-10-25")]
    report = drop(finance, "revolut-b.json", eb_file(later, balance="999.00", on="2026-10-25"))
    assert report.statements[0].reasons == ["ledger_check_failed"]


def test_csv_fallback_after_enable_banking(finance: FinanceDomain, app: typer.Typer) -> None:
    _opened(finance, app)
    report = drop(finance, "export.csv", CSV)
    first = {}
    for s in report.statements:
        first.setdefault(s.index, s)
    chf, eur = first[0], first[1]
    assert (chf.status, chf.new) == ("applied", 3)
    assert eur.reasons == ["unknown_account"]
    # le même CSV recouvert par Enable Banking : quasi-doublon signalé, rien d'écrit deux fois
    dup = [tx("r9", "4.00", "DBIT", "2026-10-25")]
    again = drop(finance, "revolut-c.json", eb_file(dup, balance=None, on="2026-10-25"))
    assert again.statements[0].reasons == ["near_duplicate"]


def test_rebuild_replays_revolut(finance: FinanceDomain, app: typer.Typer, tmp_path: Path) -> None:
    _opened(finance, app)
    drop(finance, "export.csv", CSV)
    code, out = run(app, "rebuild", "--out", str(tmp_path / "rebuilt"))
    assert code == 0, out
    assert json.loads(out.splitlines()[-1])["compare"]["ok"]


def test_pockets_of_the_same_product_keep_separate_refs() -> None:
    # Revolut UAB met le nom du titulaire comme produit de chaque poche
    refs = set()
    for i, ident in enumerate(("3aedc76c", "54c19b50", "b88abc97")):
        pocket = {
            "account_id": {"other": {"identification": ident, "scheme_name": "OTHI"}},
            "currency": "CHF",
            "cash_account_type": "SVGS",
            "product": "Titulaire Fictif",
            "identification_hash": f"hash-pocket-{i}",
        }
        refs.add(revolut.parse_eb(eb_file([], account=pocket)).statements[0].account_ref)
    assert len(refs) == 3
    assert all(r.startswith("revolut:CHF:titulaire-fictif-") for r in refs)
