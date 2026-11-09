"""Export « Trade History » de Binance (audit M15) : les ordres d'une paire retirée de la cote
(BUSD) entrent au registre comme les opérations du collecteur, une fois chacun."""

from __future__ import annotations

import pytest

from hub.domains.finance.domain import FinanceDomain
from hub.domains.finance.patrimoine.model.instruments import DocumentError
from hub.domains.finance.sources.app import binance_csv, documents
from hub.domains.finance.sources.infra.files import Incoming
from tests.finance.conftest import rows
from tests.finance.test_exchange import accounts  # noqa: F401 (fixture)

CSV = (
    "﻿Date(UTC),Pair,Side,Price,Executed,Amount,Fee\n"
    "2020-12-01 10:11:12,BTCBUSD,BUY,19000.5,0.0012BTC,22.8006BUSD,0.0000012BTC\n"
    "2020-12-01 10:11:12,BTCBUSD,BUY,19000.5,0.0012BTC,22.8006BUSD,0.0000012BTC\n"
    "2021-02-03 08:00:00,ETHBUSD,SELL,1500,0.5ETH,750BUSD,0.75BUSD\n"
)
FX = {
    "format": "hub.market.v1",
    "fetched_at": "2026-10-27",
    "fx": [
        {"on_date": d, "base": "USD", "quote": "CHF", "rate": "0.9", "source": "ecb"}
        for d in ("2020-12-01", "2021-02-03")
    ],
}


def test_detect_and_parse() -> None:
    assert documents.detect("trades.csv", CSV.encode()) == binance_csv.SOURCE
    assert documents.detect("trades.csv", b"a,b\n1,2\n") is None
    assert documents.detect("trades.txt", CSV.encode()) is None
    st = binance_csv.parse(CSV.encode())
    assert [o.id for o in st.operations] == [
        "csv:BTCBUSD:2020-12-01T101112:BUY:0.0012:22.8006:0",
        "csv:BTCBUSD:2020-12-01T101112:BUY:0.0012:22.8006:1",  # deux exécutions identiques
        "csv:ETHBUSD:2021-02-03T080000:SELL:0.5:750:0",
    ]
    sell = st.operations[-1]
    assert [(leg.symbol, str(leg.quantity), leg.role) for leg in sell.legs] == [
        ("ETH", "-0.5", "trade"),
        ("BUSD", "750", "trade"),
        ("BUSD", "-0.75", "fee"),
    ]
    with pytest.raises(DocumentError, match="désaccord"):
        binance_csv.parse(CSV.replace("BTCBUSD", "BTCUSDT").encode())
    with pytest.raises(DocumentError, match="vide"):
        binance_csv.parse(b"Date(UTC),Pair,Side,Price,Executed,Amount,Fee\n")


@pytest.mark.usefixtures("accounts")
def test_trades_land_once_in_the_journal(finance: FinanceDomain) -> None:
    import json

    finance.importer.process([Incoming("fx.json", json.dumps(FX).encode())])
    report = finance.importer.process([Incoming("trades.csv", CSV.encode())])
    assert {s.status for s in report.statements} == {"applied"}
    found = rows(
        finance,
        "SELECT e.booking_date, e.bank_tx_code, e.amount_minor, e.remittance FROM entries e "
        "JOIN accounts a ON a.id = e.account_id WHERE a.external_ref = 'crypto:binance' "
        "AND e.kind = 'movement' ORDER BY e.seq",
    )
    # chaque exécution à la valeur du stablecoin (22.8006 USD × 0.9), ses frais à part
    assert found == [
        ("2020-12-01", "EXCHANGE/TRADE/BUY", 2_052, "0.0012 BTC"),
        ("2020-12-01", "EXCHANGE/TRADE/SELL", -2_052, "-22.8006 BUSD"),
        ("2020-12-01", "EXCHANGE/FEE", -2, "-0.0000012 BTC"),
        ("2020-12-01", "EXCHANGE/TRADE/BUY", 2_052, "0.0012 BTC"),
        ("2020-12-01", "EXCHANGE/TRADE/SELL", -2_052, "-22.8006 BUSD"),
        ("2020-12-01", "EXCHANGE/FEE", -2, "-0.0000012 BTC"),
        ("2021-02-03", "EXCHANGE/TRADE/SELL", -67_500, "-0.5 ETH"),
        ("2021-02-03", "EXCHANGE/TRADE/BUY", 67_500, "750 BUSD"),
        ("2021-02-03", "EXCHANGE/FEE", -68, "-0.75 BUSD"),
    ]
    again = finance.importer.process([Incoming("trades-longer.csv", CSV.encode())])
    assert sum(s.new for s in again.statements) == 0  # un export plus long : rien en double
    moves = rows(finance, "SELECT isin, quantity FROM trades ORDER BY seq")
    assert ("CRYPTO:ETH", "-0.5") in {(m[0], str(m[1])) for m in moves}


# export « Historique des trades Spot » en français, chiffres inventés ; l'ordre 9 est celui que
# l'API a déjà lu (test_exchange : trade:BTCUSDT:9:100), l'ordre 77 arrive en deux exécutions
CSV_FR = (
    "﻿N° de commande,Durée,Paire,Côté,Prix,Exécuté,Montant,Frais,"
    "Paire de conversion AOR,Taux de conversion AOR\r\n"
    "9,2026-03-03 00:30:00,BTCUSDT,BUY,60000,0.001BTC,60USDT,0.00008BNB,,\r\n"
    "77,2026-03-04 10:00:00,ETHUSDT,BUY,2000,0.1ETH,200USDT,0.0001ETH,,\r\n"
    "77,2026-03-04 10:00:01,ETHUSDT,BUY,2000,0.05ETH,100USDT,0.00005ETH,,\r\n"
)


def test_french_export_groups_an_order() -> None:
    assert documents.detect("trades.csv", CSV_FR.encode()) == binance_csv.SOURCE
    st = binance_csv.parse(CSV_FR.encode())
    assert [o.id for o in st.operations] == ["csv:BTCUSDT:order:9", "csv:ETHUSDT:order:77"]
    eth = st.operations[-1]
    assert [(leg.symbol, str(leg.quantity), leg.role) for leg in eth.legs] == [
        ("ETH", "0.15", "trade"),
        ("USDT", "-300", "trade"),
        ("ETH", "-0.00015", "fee"),
    ]


@pytest.mark.usefixtures("accounts")
def test_french_export_skips_orders_the_api_already_read(finance: FinanceDomain) -> None:
    import json

    from tests.finance.test_exchange import BINANCE

    finance.importer.process([Incoming("binance.json", json.dumps(BINANCE).encode())])
    before = rows(finance, "SELECT count(*) FROM entries WHERE kind = 'movement'")[0][0]
    finance.importer.process([Incoming("trades.csv", CSV_FR.encode())])
    eth = rows(
        finance,
        "SELECT m.asset, m.quantity FROM crypto_moves m JOIN entries e ON e.seq = m.entry_seq "
        "WHERE m.role = 'trade' AND e.booking_date = '2026-03-04' ORDER BY e.seq",
    )
    assert eth == [("ETH", "0.15"), ("USDT", "-300")]  # seul l'ordre 77 entre
    btc = rows(
        finance,
        "SELECT count(*) FROM crypto_moves WHERE role = 'trade' AND asset = 'BTC'",
    )
    assert btc == [(1,)]  # l'ordre 9 n'est pas compté deux fois
    after = rows(finance, "SELECT count(*) FROM entries WHERE kind = 'movement'")[0][0]
    assert after - before == 3  # achat, vente, frais de l'ordre 77
