"""L1-06 et L1-13 : service d'import, rapprochement, archivage chiffré, reprise d'historique."""

import os
import time
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from hub.core import secrets
from hub.domains.finance import importer
from hub.domains.finance.domain import FinanceDomain
from hub.domains.finance.importer import Incoming
from tests.factories.camt import IBAN, IBAN_2, Detail, Stmt, Tx, camt053, zipped
from tests.finance.conftest import D, add_account, ledger_state, ready_account, rows, simple_stmt


def drop(domain: FinanceDomain, name: str, data: bytes) -> Path:
    inbox = domain.settings.paths.inbox
    inbox.mkdir(parents=True, exist_ok=True)
    path = inbox / name
    path.write_bytes(data)
    old = time.time() - 60  # fichier « posé » depuis longtemps
    os.utime(path, (old, old))
    return path


def statuses(domain: FinanceDomain) -> list[str]:
    return [str(r[0]) for r in rows(domain, "SELECT status FROM imports ORDER BY received_at")]


def test_inbox_import_applies_and_archives_encrypted(finance: FinanceDomain) -> None:
    ready_account(finance, 100_000)
    data = camt053(simple_stmt("1000.00"))
    path = drop(finance, "releve.xml", data)
    report = finance.importer.process_inbox()
    assert report.counters()["new_entries"] == 3
    assert statuses(finance) == ["applied"]
    assert not path.exists()
    (archive_path,) = rows(finance, "SELECT archive_path FROM imports")
    stored = finance.settings.paths.archive / str(archive_path[0])
    assert stored.suffix == ".age"
    assert b"Jean Exemple" not in stored.read_bytes()  # chiffré
    key = finance.settings.secrets.age_key_file
    assert secrets.decrypt_with(key, stored.read_bytes()) == data
    assert rows(finance, "SELECT kind, on_date, amount_minor FROM checkpoints ORDER BY kind") == [
        ("CLBD", "2026-10-02", 346000),
        ("OPBD", "2026-10-01", 100000),
    ]
    events = rows(finance, "SELECT type FROM events ORDER BY seq")
    assert events == [("entries.appended",), ("import.applied",)]
    assert finance.verify_ledger().ok


def test_same_file_again_goes_to_duplicates(finance: FinanceDomain) -> None:
    ready_account(finance)
    data = camt053(simple_stmt())
    finance.importer.process([Incoming("a.xml", data)])
    report = finance.importer.process([Incoming("b.xml", data)])
    assert [f.status for f in report.files] == ["duplicate"]
    assert list((finance.settings.paths.archive / "duplicates").iterdir())
    assert len(rows(finance, "SELECT 1 FROM entries WHERE kind = 'movement'")) == 3


def test_overlapping_export_only_adds_new_days(finance: FinanceDomain) -> None:
    ready_account(finance)
    first = simple_stmt("1000.00")
    finance.importer.process([Incoming("a.xml", camt053(first, "04"))])
    later = Stmt(
        opening=Decimal("1000.00"),
        opening_date=D,
        entries=[*first.entries, Tx("5.00", True, date(2026, 10, 3))],
        stmt_id="S2",
    )
    report = finance.importer.process([Incoming("b.xml", camt053(later, "08"))])
    (s,) = report.statements
    assert (s.status, s.new, s.duplicates) == ("applied", 1, 3)
    assert finance.verify_ledger().ok


def test_unknown_account_waits_then_retries_after_accounts_add(finance: FinanceDomain) -> None:
    report = finance.importer.process([Incoming("a.xml", camt053(simple_stmt()))])
    assert report.statements[0].reasons == ["unknown_account"]
    assert statuses(finance) == ["needs_review"]
    a = add_account(finance)
    retried = finance.importer.retry_needs_review()
    assert retried[0].reasons == ["no_opening"]
    from tests.finance.conftest import open_account

    open_account(finance, a, "2026-09-30", 100_000)
    retried = finance.importer.retry_needs_review()
    assert [r.status for r in retried] == ["applied"]
    assert statuses(finance) == ["applied"]


def test_balance_gap_stays_in_review_with_readable_reason(finance: FinanceDomain) -> None:
    ready_account(finance, 50_000)  # ouverture ≠ OPBD du relevé : écart de registre
    report = finance.importer.process([Incoming("a.xml", camt053(simple_stmt("1000.00")))])
    assert report.statements[0].reasons == ["ledger_check_failed"]
    assert len(rows(finance, "SELECT 1 FROM entries")) == 1  # rien d'écrit
    bad = simple_stmt("500.00", closing=Decimal("1.00"))
    report = finance.importer.process([Incoming("b.xml", camt053(bad))])
    assert "internal_check_failed" in report.statements[0].reasons


def test_missing_month_is_applied_once_it_arrives(finance: FinanceDomain) -> None:
    ready_account(finance, 100_000)
    oct_ = simple_stmt("1000.00")
    nov = Stmt(
        opening=oct_.computed_closing(),
        opening_date=date(2026, 11, 1),
        entries=[Tx("10.00", True, date(2026, 11, 2))],
        stmt_id="NOV",
    )
    finance.importer.process([Incoming("nov.xml", camt053(nov))])
    assert statuses(finance) == ["needs_review"]
    report = finance.importer.process([Incoming("oct.xml", camt053(oct_))])
    assert [s.status for s in report.statements] == ["applied", "applied"]  # novembre rejoué
    assert statuses(finance) == ["applied", "applied"]


def test_checkpoints_repeated_are_ignored_and_contradictory_wait(finance: FinanceDomain) -> None:
    ready_account(finance, 100_000)
    s1 = simple_stmt("1000.00")
    finance.importer.process([Incoming("a.xml", camt053(s1))])
    same_day = Stmt(Decimal("1000.00"), D, s1.entries, stmt_id="AGAIN")
    report = finance.importer.process([Incoming("b.xml", camt053(same_day, "04"))])
    assert report.statements[0].status == "applied"
    clash = Stmt(Decimal("999.00"), D, [], closing_date=D, stmt_id="CLASH", closing=Decimal(999))
    report = finance.importer.process([Incoming("c.xml", camt053(clash))])
    assert "checkpoint_conflict" in report.statements[0].reasons


def test_near_duplicate_is_flagged(finance: FinanceDomain) -> None:
    ready_account(finance, 100_000)
    a = Stmt(Decimal("1000.00"), D, [Tx("20.00", True, D, label="TWINT")], stmt_id="A")
    finance.importer.process([Incoming("a.xml", camt053(a))])
    b = Stmt(Decimal("1000.00"), D, [Tx("20.00", True, D, label="TWINT corrigé")], stmt_id="B")
    report = finance.importer.process([Incoming("b.xml", camt053(b))])
    assert "near_duplicate" in report.statements[0].reasons


def test_grouped_entry_not_split_waits(finance: FinanceDomain) -> None:
    ready_account(finance, 100_000)
    s = Stmt(
        Decimal("1000.00"),
        D,
        [Tx("50.00", True, D, details=[Detail("20.00"), Detail("31.00")])],
    )
    report = finance.importer.process([Incoming("a.xml", camt053(s))])
    assert report.statements[0].reasons == ["grouped_not_split"]


def test_transfer_between_own_accounts_is_categorized(finance: FinanceDomain) -> None:
    ready_account(finance, 100_000)
    add_account(finance, IBAN_2, external_ref=None)
    s = Stmt(Decimal("1000.00"), D, [Tx("200.00", True, D, counterparty_iban=IBAN_2)])
    finance.importer.process([Incoming("a.xml", camt053(s))])
    assert rows(finance, "SELECT category_id, source, rule_id FROM categorizations") == [
        ("transfer-own", "rule", "system-transfer-own")
    ]


def test_zip_with_several_statements_in_any_order(finance: FinanceDomain) -> None:
    ready_account(finance, 100_000)
    oct_ = simple_stmt("1000.00")
    nov = Stmt(
        oct_.computed_closing(),
        date(2026, 11, 1),
        [Tx("10.00", True, date(2026, 11, 2))],
        stmt_id="NOV",
    )
    archive = zipped({"2-nov.xml": camt053(nov), "1-oct.xml": camt053(oct_, "04"), "x.txt": b""})
    drop(finance, "export.zip", archive)
    report = finance.importer.process_inbox()
    assert report.counters()["applied"] == 2
    assert report.counters()["needs_review"] == 0
    assert statuses(finance) == ["applied", "applied"]


def test_bad_zip_and_invalid_file_are_rejected(finance: FinanceDomain) -> None:
    report = finance.importer.process([Incoming("a.zip", b"not a zip")])
    assert report.files[0].reason == "import.invalid_schema"
    report = finance.importer.process([Incoming("b.xml", b"<Document/>")])
    assert report.files[0].status == "rejected"
    assert statuses(finance) == ["rejected"]


def test_inbox_skips_files_still_being_copied_and_pauses_during_history(
    finance: FinanceDomain,
) -> None:
    ready_account(finance)
    inbox = finance.settings.paths.inbox
    inbox.mkdir(parents=True)
    (inbox / "fresh.xml").write_bytes(camt053(simple_stmt()))
    (inbox / ".hidden.xml").write_bytes(b"")
    (inbox / "notes.txt").write_bytes(b"")
    assert finance.importer.process_inbox().files == []
    finance.importer.lock_file.touch()
    drop(finance, "old.xml", camt053(simple_stmt()))
    assert finance.importer.process_inbox().files == []
    with pytest.raises(importer.ImportRefused):
        finance.importer.receive("x.xml", b"")


def test_archive_needs_a_key(tmp_path: Path, finance: FinanceDomain) -> None:
    archiver = importer.Archiver(tmp_path, None, None)
    with pytest.raises(importer.ImportRefused):
        archiver.store(b"x", "sub", "name")
    with pytest.raises(importer.ImportRefused):
        archiver.load("x")
    assert importer.recipient_from_key(tmp_path / "absent") is None
    # archive illisible : refus explicite, ou rien en mode silencieux
    report = finance.importer.process([Incoming("a.xml", camt053(simple_stmt()))])
    assert report.statements[0].reasons == ["unknown_account"]
    (path,) = rows(finance, "SELECT archive_path FROM imports")
    (finance.settings.paths.archive / str(path[0])).write_bytes(b"abime")
    assert finance.importer.retry_needs_review(quiet=True) == []
    with pytest.raises(importer.ImportRefused):
        finance.importer.retry_needs_review()


def test_unordered_batch_gives_same_ledger(fsettings: object, tmp_path: Path) -> None:
    from tests.finance.conftest import finance_settings

    oct_ = simple_stmt("1000.00")
    nov = Stmt(oct_.computed_closing(), date(2026, 11, 1), [Tx("1.00", True, date(2026, 11, 3))])
    files = [Incoming("oct.xml", camt053(oct_)), Incoming("nov.xml", camt053(nov))]
    states = []
    for i, order in enumerate((files, files[::-1])):
        d = FinanceDomain(finance_settings(tmp_path / str(i)))
        d.migrate()
        a = add_account(d)
        from tests.finance.conftest import open_account

        open_account(d, a, "2026-09-30", 100_000)
        d.importer.process(order)
        states.append([s[2:] for s in ledger_state(d)])  # sans id ni compte (ULID)
        d.engine().dispose()
    assert states[0] == states[1]


# --- reprise d'historique ------------------------------------------------------------------


def _months(start: date, n: int, opening: Decimal = Decimal("500.00")) -> list[Stmt]:
    out = []
    balance = opening
    for i in range(n):
        first = date(start.year + (start.month - 1 + i) // 12, (start.month - 1 + i) % 12 + 1, 1)
        s = Stmt(
            balance,
            first,
            [
                Tx("12.00", True, first + timedelta(days=2)),
                Tx("40.00", False, first + timedelta(9)),
            ],
            stmt_id=f"M{i}",
        )
        out.append(s)
        balance = s.computed_closing()
    return out


def _folder(tmp_path: Path, stmts: list[Stmt], names: list[str] | None = None) -> Path:
    folder = tmp_path / "history"
    folder.mkdir(parents=True, exist_ok=True)
    for i, s in enumerate(stmts):
        name = names[i] if names else f"{i:03d}.xml"
        (folder / name).write_bytes(camt053(s, "04" if i % 2 else "08"))
    return folder


def test_history_opens_and_applies_everything(finance: FinanceDomain, tmp_path: Path) -> None:
    add_account(finance)
    folder = _folder(tmp_path, _months(date(2016, 1, 1), 6))
    report = importer.import_history(finance.importer, folder)
    assert report.ok, report.public()
    assert report.batch["applied"] == 6
    assert report.accounts[0]["entries"] == 12
    assert report.accounts[0]["account"] == "CH93…957"
    assert rows(finance, "SELECT booking_date, amount_minor FROM entries WHERE kind='opening'") == [
        ("2015-12-31", 50000)  # veille du premier jour du relevé le plus ancien
    ]
    assert not finance.importer.lock_file.exists()
    again = importer.import_history(
        finance.importer, _folder(tmp_path / "b", _months(date(2015, 1, 1), 2))
    )
    assert not again.ok
    assert "déjà ouvert" in (again.error or "")


def test_history_order_does_not_matter(tmp_path: Path) -> None:
    """Sur fixtures : 2016 puis 2024, ou l'inverse, donne le même registre."""
    from tests.finance.conftest import finance_settings

    early = _months(date(2016, 1, 1), 3)
    late = _months(date(2016, 4, 1), 3, early[-1].computed_closing())
    states = []
    for i, names in enumerate((["a-2016.xml", "b-2024.xml"], ["b-2016.xml", "a-2024.xml"])):
        d = FinanceDomain(finance_settings(tmp_path / str(i)))
        d.migrate()
        add_account(d)
        folder = tmp_path / f"h{i}"
        folder.mkdir()
        (folder / names[0]).write_bytes(camt053(early))
        (folder / names[1]).write_bytes(camt053(late, "04"))
        assert importer.import_history(d.importer, folder).ok
        states.append([s[2:] for s in ledger_state(d)])
        d.engine().dispose()
    assert states[0] == states[1]


def test_history_hole_stops_before_writing(finance: FinanceDomain, tmp_path: Path) -> None:
    add_account(finance)
    months = _months(date(2016, 1, 1), 4)
    folder = _folder(tmp_path, [months[0], months[1], months[3]])
    report = importer.import_history(finance.importer, folder)
    assert not report.ok
    assert report.missing == [{"account": "CH93…957", "from": "2016-02-10", "to": "2016-04-01"}]
    assert rows(finance, "SELECT count(*) FROM entries") == [(0,)]


def test_history_refusals(finance: FinanceDomain, tmp_path: Path) -> None:
    folder = _folder(tmp_path, _months(date(2016, 1, 1), 1))
    assert "inconnu" in (importer.import_history(finance.importer, folder).error or "")
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "x.xml").write_bytes(b"<x/>")
    assert "import.invalid_schema" in (importer.import_history(finance.importer, bad).error or "")
    finance.importer.lock_file.parent.mkdir(parents=True, exist_ok=True)
    finance.importer.lock_file.touch()
    with pytest.raises(importer.ImportRefused):
        importer.import_history(finance.importer, folder)


def test_opening_only_once(finance: FinanceDomain) -> None:
    a = ready_account(finance)
    from hub.core.db import begin_immediate

    with pytest.raises(importer.ImportRefused), begin_immediate(finance.engine()) as conn:
        importer.open_account(conn, a.id, "2020-01-01", 1, "CHF")
    s = Stmt(Decimal("1000.00"), date(2026, 9, 1), [Tx("1.00", True, date(2026, 9, 2))])
    report = finance.importer.process([Incoming("old.xml", camt053(s))])
    assert "before_opening" in report.statements[0].reasons
    assert IBAN
