"""Relevé SwissBorg (.xlsx) : soldes par actif rejoués, relevés de positions, cours et change."""

from __future__ import annotations

import io
import json
import zipfile
from decimal import Decimal
from xml.sax.saxutils import escape

import pytest

from hub.domains.finance import catalog, insights, market, swissborg, transfers, valuation, xlsx
from hub.domains.finance.domain import FinanceDomain
from hub.domains.finance.importer import ImportRefused, Incoming
from hub.platform.db import begin_immediate
from tests.finance.conftest import rows

NS = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
RNS = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
PKG = 'xmlns="http://schemas.openxmlformats.org/package/2006/relationships"'


def _col(j: int) -> str:
    return chr(65 + j)


def _put(z: zipfile.ZipFile, name: str, text: str) -> None:
    """Membre à date fixe : le même classeur donne les mêmes octets (doublon reconnu)."""
    z.writestr(zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0)), text)


def workbook(table: list[tuple[int, list[object]]], shared: bool = False) -> bytes:
    """Classeur minimal : (n° de ligne Excel, cellules) ; texte en ligne ou partagé."""
    strings: list[str] = []
    out = []
    for n, cells in table:
        xml = []
        for j, v in enumerate(cells):
            ref = f"{_col(j)}{n}"
            if isinstance(v, str) and shared:
                strings.append(v)
                xml.append(f'<c r="{ref}" t="s"><v>{len(strings) - 1}</v></c>')
            elif isinstance(v, str):
                xml.append(f'<c r="{ref}" t="inlineStr"><is><t>{escape(v)}</t></is></c>')
            else:
                xml.append(f'<c r="{ref}" t="n"><v>{v}</v></c>')
        out.append(f'<row r="{n}">{"".join(xml)}</row>')
    sheet = f"<worksheet {NS}><sheetData>{''.join(out)}</sheetData></worksheet>"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        _put(
            z,
            "xl/workbook.xml",
            f'<workbook {NS} {RNS}><sheets><sheet name="Transactions" r:id="rId3" sheetId="1"/>'
            "</sheets></workbook>",
        )
        _put(
            z,
            "xl/_rels/workbook.xml.rels",
            f'<Relationships {PKG}><Relationship Id="rId3" Target="worksheets/sheet1.xml" '
            'Type="worksheet"/></Relationships>',
        )
        _put(z, "xl/worksheets/sheet1.xml", sheet)
        if shared:
            sst = "".join(f"<si><t>{escape(s)}</t></si>" for s in strings)
            _put(z, "xl/sharedStrings.xml", f"<sst {NS}>{sst}</sst>")
    return buf.getvalue()


def move(
    when: str, kind: str, ccy: str, gross: str, usd: str, fee: str = "0", note: str = ""
) -> list[object]:
    net = Decimal(gross) - Decimal(fee)
    fee_usd = Decimal(usd) * Decimal(fee) / Decimal(gross) if Decimal(gross) else Decimal(0)
    net_usd = Decimal(usd) - fee_usd
    return [
        f"{when}:00",
        f"{when}:00",
        kind,
        ccy,
        gross,
        usd,
        fee,
        str(fee_usd),
        str(net),
        str(net_usd),
        note,
    ]


MOVES = [
    move("2026-10-01 10:00", "Deposit", "CHF", "1000", "1250"),
    move("2026-10-01 10:05", "Sell", "CHF", "800", "1000"),
    move("2026-10-01 10:05", "Buy", "BTC", "0.02", "1000", fee="0.0001"),
    move("2026-10-03 08:00", "Payouts", "BTC", "0.0001", "6"),
    move("2026-10-05 09:00", "Withdrawal", "BTC", "0.01", "550", fee="0.0002"),
    # frais périodique : brut nul, net négatif
    [
        "2026-10-06 00:00:00",
        "2026-10-06 00:00:00",
        "Withdrawal",
        "BTC",
        "0",
        "0",
        "0.0004",
        "20",
        "-0.0004",
        "-20",
        "Periodic fee",
    ],
]


def statement(moves: list[list[object]] = MOVES, shared: bool = False) -> bytes:
    head: list[tuple[int, list[object]]] = [
        (4, ["SwissBorg", "", "", "Name", "Test"]),
        (14, list(swissborg.HEADER)),
    ]
    return workbook(head + [(15 + i, m) for i, m in enumerate(moves)], shared=shared)


def test_xlsx_rows_keep_excel_numbering_and_shared_strings() -> None:
    table = xlsx.rows(statement(shared=True))
    assert table[13] == list(swissborg.HEADER)
    assert table[3][:4] == ["SwissBorg", "", "", "Name"]
    assert table[14][2:5] == ["Deposit", "CHF", "1000"]


def test_balances_are_replayed_day_by_day() -> None:
    data = statement()
    assert swissborg.detect("account_statement.xlsx", data) == swissborg.SOURCE
    assert swissborg.detect("autre.xlsx", workbook([(1, ["a", "b"])])) is None
    assert swissborg.detect("account_statement.csv", data) is None
    doc = swissborg.parse(data)
    assert [d.snapshot.on_date for d in doc.days] == [
        "2026-10-01",
        "2026-10-03",
        "2026-10-05",
        "2026-10-06",
    ]
    first = {r.key: (r.quantity, r.price, r.currency) for r in doc.days[0].snapshot.rows}
    assert first == {
        "SYM:CHF": (Decimal(200), Decimal(1), "CHF"),
        "CRYPTO:BTC": (Decimal("0.0199"), Decimal(50000), "USD"),
    }
    assert doc.days[0].usd_chf == Decimal("0.8")
    last = {r.key: r.quantity for r in doc.days[-1].snapshot.rows}
    # 0.0199 + 0.0001 de rendement - 0.01 retirés - 0.0004 de frais
    assert last == {"SYM:CHF": Decimal(200), "CRYPTO:BTC": Decimal("0.0096")}
    # pas de mouvement en BTC avec contre-valeur ce jour-là : dernier cours connu
    assert doc.days[-1].snapshot.rows[0].price == 0


def test_refusals() -> None:
    with pytest.raises(swissborg.SwissborgError, match="type de mouvement"):
        swissborg.parse(statement([move("2026-10-01 10:00", "Airdrop", "BTC", "1", "1")]))
    with pytest.raises(swissborg.SwissborgError, match="négatif"):
        swissborg.parse(statement([move("2026-10-01 10:00", "Sell", "BTC", "1", "1")]))
    with pytest.raises(swissborg.SwissborgError, match="date"):
        swissborg.parse(statement([["hier", "hier", "Buy", "BTC", "1", "1", "0", "0", "1"]]))
    with pytest.raises(swissborg.SwissborgError, match="illisible"):
        swissborg.parse(statement([move("2026-10-01 10:00", "Buy", "BTC", "-1", "1")]))
    with pytest.raises(swissborg.SwissborgError, match="sans mouvement"):
        swissborg.parse(statement([]))
    with pytest.raises(swissborg.SwissborgError, match="pas un relevé"):
        swissborg.parse(workbook([(1, ["Date", "Montant"])]))
    with pytest.raises(swissborg.SwissborgError, match="illisible"):
        swissborg.parse(b"PK\x03\x04 pas un zip")


def test_import_values_history_and_arrival_cost(finance: FinanceDomain) -> None:
    report = finance.importer.process([Incoming("account_statement.xlsx", statement())])
    assert {s.status for s in report.statements} == {"needs_review"}  # compte pas déclaré
    with begin_immediate(finance.engine()) as conn:
        catalog.add_account(
            conn,
            institution="SwissBorg",
            name="SwissBorg",
            kind="crypto",
            external_ref=swissborg.ACCOUNT,
            currency="CHF",
        )
    finance.importer.retry_needs_review()
    assert rows(finance, "SELECT count(*) FROM holdings") == [(8,)]
    assert rows(finance, "SELECT rate FROM fx_rates WHERE source = 'swissborg'") == [("0.8",)]
    with finance.engine().connect() as conn:
        v = valuation.value_at(conn, "2026-10-02")
        later = valuation.value_at(conn, "2026-10-27")
        h = insights.holdings(conn, "2026-10-27")
    # 200 CHF en attente + 0.0199 BTC à 50 000 USD (0.8 CHF)
    assert v.by_envelope["crypto"] == 20_000 + 79_600
    # 0.0096 BTC au dernier cours du fichier (55 000 USD le 5)
    assert later.by_envelope["crypto"] == 20_000 + 42_240
    # coût des parts : 0.0199 achetés 796 CHF net de frais, 0.0001 reçus en rendement 4.80,
    # puis la moitié retirée et 0.0004 de frais : 38.04 % du coût reste
    btc = {i["isin"]: i for i in h["items"]}["CRYPTO:BTC"]
    assert btc["cost"]["minor"] == 38_438
    # les opérations sont au registre, en CHF au change du relevé, catégorisées par leur code
    ops = rows(
        finance,
        "SELECT e.bank_tx_code, e.amount_minor, vc.category_id FROM entries e "
        "LEFT JOIN v_entry_category vc ON vc.entry_seq = e.seq "
        "WHERE e.kind = 'movement' ORDER BY e.booking_date, e.seq",
    )
    assert ops == [
        ("SWISSBORG/DEPOSIT", 100_000, "transfer-own"),
        ("SWISSBORG/TRADE/SELL", -80_000, "transfer-titres"),
        ("SWISSBORG/TRADE/BUY", 80_000, "transfer-titres"),
        ("SWISSBORG/FEE/TRADE", -400, "frais-placement"),
        ("SWISSBORG/INCOME/YIELD", 480, "rendement"),
        ("SWISSBORG/WITHDRAWAL", -43_120, "transfer-own"),
        ("SWISSBORG/FEE/WITHDRAWAL", -880, "frais-placement"),
        ("SWISSBORG/FEE/PERIODIC", -1_600, "frais-placement"),
    ]
    assert rows(finance, "SELECT count(*) FROM trades") == [(6,)]
    # le net d'un retrait (ce qui arrive sur la Ledger) est gardé pour l'apparier
    sent = rows(
        finance,
        "SELECT remittance, json_extract(fx_json, '$.quantity') FROM entries "
        "WHERE bank_tx_code = 'SWISSBORG/WITHDRAWAL'",
    )
    assert sent == [("-0.0098 BTC", "-0.0098")]
    # rien de tout ça n'est un versement au patrimoine
    assert later.deposits == 0
    # le même relevé redéposé est un doublon ; le rejouer n'ajoute rien
    again = finance.importer.process([Incoming("copie.xlsx", statement())])
    assert [f.status for f in again.files] == ["duplicate"]
    replayed = finance.importer.replay(swissborg.SOURCE)
    assert {o.status for o in replayed} == {"applied"}
    assert sum(o.new for o in replayed) == 0
    assert rows(finance, "SELECT count(*) FROM entries") == [(9,)]


def test_replay_writes_operations_of_an_earlier_import(
    finance: FinanceDomain, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Un relevé importé avant les opérations au registre (positions seules) : `replay` les
    ajoute depuis l'archive, sans doubler les positions."""
    with begin_immediate(finance.engine()) as conn:
        catalog.add_account(
            conn,
            institution="SwissBorg",
            name="SwissBorg",
            kind="crypto",
            external_ref=swissborg.ACCOUNT,
            currency="CHF",
        )
    with monkeypatch.context() as m:
        m.setattr(swissborg, "_write_move", lambda *_a: None)
        finance.importer.process([Incoming("account_statement.xlsx", statement())])
    assert rows(finance, "SELECT count(*) FROM entries WHERE kind = 'movement'") == [(0,)]
    replayed = finance.importer.replay(swissborg.SOURCE)
    assert sum(o.new for o in replayed) == 8  # les écritures ; les 8 positions sont des doublons
    assert sum(o.duplicates for o in replayed) == 8
    assert rows(finance, "SELECT count(*) FROM entries WHERE kind = 'movement'") == [(8,)]
    with pytest.raises(ImportRefused):
        finance.importer.replay("inconnue")


def test_ledger_transactions_pair_with_swissborg_withdrawals(finance: FinanceDomain) -> None:
    """Une arrivée sur la Ledger de la quantité nette d'un retrait SwissBorg prend sa valeur
    et devient un virement entre mes comptes ; un envoi sépare ses frais de réseau."""
    with begin_immediate(finance.engine()) as conn:
        for ref, name in [(swissborg.ACCOUNT, "SwissBorg"), ("crypto:ledger", "Ledger")]:
            catalog.add_account(
                conn, institution=name, name=name, kind="crypto", external_ref=ref, currency="CHF"
            )
    finance.importer.process([Incoming("account_statement.xlsx", statement())])
    doc = {
        "format": market.FORMAT,
        "fetched_at": "2026-10-27",
        "prices": [
            {
                "instrument": "BTC",
                "kind": "crypto",
                "on_date": "2026-10-01",
                "price": "50000",
                "currency": "CHF",
                "source": "coingecko",
            }
        ],
        "transactions": [
            {
                "account": "crypto:ledger",
                "instrument": "BTC",
                "on_date": "2026-10-06",
                "txid": "aa11",
                "quantity": "0.0098",
                "fee": "0",
            },
            {
                "account": "crypto:ledger",
                "instrument": "BTC",
                "on_date": "2026-10-20",
                "txid": "bb22",
                "quantity": "-0.005",
                "fee": "0.0001",
            },
        ],
    }
    report = finance.importer.process([Incoming("market.json", json.dumps(doc).encode())])
    assert {s.status for s in report.statements} == {"applied"}
    ledger_ops = rows(
        finance,
        "SELECT e.bank_tx_code, e.amount_minor, vc.category_id FROM entries e "
        "JOIN accounts a ON a.id = e.account_id "
        "LEFT JOIN v_entry_category vc ON vc.entry_seq = e.seq "
        "WHERE a.external_ref = 'crypto:ledger' AND e.kind = 'movement' ORDER BY e.seq",
    )
    assert ledger_ops == [
        ("CRYPTO/RECEIVE", 43_120, "transfer-own"),  # la valeur du retrait SwissBorg
        # dernier cours connu : celui du relevé SwissBorg du 5 (55 000 USD à 0.8)
        ("CRYPTO/SEND", -21_560, "transfer-own"),  # 0.0049 BTC
        ("CRYPTO/FEE", -440, "frais-placement"),
    ]
    with begin_immediate(finance.engine()) as conn:
        transfers.refresh(conn)
    paired = rows(
        finance,
        "SELECT d.bank_tx_code, c.bank_tx_code FROM transfer_links t "
        "JOIN entries d ON d.seq = t.debit_seq JOIN entries c ON c.seq = t.credit_seq",
    )
    assert ("SWISSBORG/WITHDRAWAL", "CRYPTO/RECEIVE") in paired
    with finance.engine().connect() as conn:
        h = insights.holdings(conn, "2026-10-27")
    btc = {(i["account"], i["isin"]): i for i in h["items"]}[("Ledger", "CRYPTO:BTC")]
    # 0.0048 restent : leur part du coût d'arrivée (43 120 × 0.0048 / 0.0098)
    assert (btc["quantity"], btc["cost"]["minor"], btc["value"]["minor"]) == (
        "0.0048",
        21_120,
        21_120,
    )
