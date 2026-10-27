"""Relevés Flex Query IBKR fictifs (aucune donnée réelle) : la forme d'une requête « Activity »
avec AccountInformation, CashReport, OpenPositions, Trades, CashTransactions et
ConversionRates, dates au format par défaut d'IBKR (aaaammjj)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from xml.sax.saxutils import quoteattr

ACCOUNT = "U0000001"
VT = ("US9220427424", "VT", "VANGUARD TOT WORLD STK ETF")
CHSPI = ("CH0237935652", "CHSPI", "ISHARES CORE SPI CH")


def d8(d: date) -> str:
    return d.strftime("%Y%m%d")


def _attrs(**kw: object) -> str:
    return " ".join(f"{k}={quoteattr(str(v))}" for k, v in kw.items() if v is not None)


@dataclass
class Flex:
    from_date: date
    to_date: date
    account: str = ACCOUNT
    base: str = "CHF"
    cash: list[tuple[str, str, str]] = field(default_factory=list)  # devise, départ, fin
    positions: list[dict[str, object]] | None = None
    trades: list[dict[str, object]] = field(default_factory=list)
    cash_txs: list[dict[str, object]] = field(default_factory=list)
    rates: list[tuple[str, str]] = field(default_factory=list)  # devise, cours vers CHF

    def statement(self) -> str:
        parts = [
            f"<FlexStatement {_attrs(accountId=self.account, fromDate=d8(self.from_date), toDate=d8(self.to_date), period='Custom', whenGenerated=d8(self.to_date) + ';101010')}>",
            f"<AccountInformation {_attrs(accountId=self.account, currency=self.base, name='Personne Fictive')} />",
            "<CashReport>",
            f"<CashReportCurrency {_attrs(accountId=self.account, currency='BASE_SUMMARY', startingCash='0', endingCash='0')} />",
        ]
        parts += [
            f"<CashReportCurrency {_attrs(accountId=self.account, currency=c, startingCash=s, endingCash=e)} />"
            for c, s, e in self.cash
        ]
        parts.append("</CashReport>")
        if self.positions is not None:
            parts.append("<OpenPositions>")
            for p in self.positions:
                parts.append(
                    f"<OpenPosition {_attrs(accountId=self.account, levelOfDetail='SUMMARY', reportDate=d8(self.to_date), **p)} />"
                )
            parts.append("</OpenPositions>")
        parts.append("<Trades>")
        parts += [f"<Trade {_attrs(accountId=self.account, **t)} />" for t in self.trades]
        parts.append("</Trades><CashTransactions>")
        parts += [
            f"<CashTransaction {_attrs(accountId=self.account, levelOfDetail='DETAIL', **c)} />"
            for c in self.cash_txs
        ]
        parts.append("</CashTransactions><ConversionRates>")
        parts += [
            f"<ConversionRate {_attrs(reportDate=d8(self.to_date), fromCurrency=c, toCurrency='CHF', rate=r)} />"
            for c, r in self.rates
        ]
        parts.append("</ConversionRates></FlexStatement>")
        return "".join(parts)


def flex(*statements: Flex) -> bytes:
    body = "".join(s.statement() for s in statements)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<FlexQueryResponse queryName="hub" type="AF"><FlexStatements count="{len(statements)}">'
        f"{body}</FlexStatements></FlexQueryResponse>"
    ).encode()


def buy(
    tx: str,
    on: date,
    fund: tuple[str, str, str],
    qty: str,
    price: str,
    proceeds: str,
    *,
    currency: str = "USD",
    commission: str = "-1.00",
    fx: str = "0.80",
    sell: bool = False,
) -> dict[str, object]:
    isin, symbol, name = fund
    return {
        "transactionID": tx,
        "tradeID": tx,
        "assetCategory": "STK",
        "symbol": symbol,
        "isin": isin,
        "conid": "1" + tx,
        "description": name,
        "currency": currency,
        "tradeDate": d8(on),
        "dateTime": d8(on) + ";153000",
        "quantity": ("-" if sell else "") + qty,
        "tradePrice": price,
        "proceeds": proceeds,
        "ibCommission": commission,
        "ibCommissionCurrency": currency,
        "buySell": "SELL" if sell else "BUY",
        "fxRateToBase": fx,
        "levelOfDetail": "EXECUTION",
    }


def fx_trade(tx: str, on: date, pair: str, qty: str, rate: str, proceeds: str) -> dict[str, object]:
    return {
        "transactionID": tx,
        "assetCategory": "CASH",
        "symbol": pair,
        "description": pair,
        "currency": pair.split(".")[1],
        "tradeDate": d8(on),
        "quantity": qty,
        "tradePrice": rate,
        "proceeds": proceeds,
        "ibCommission": "-2.00",
        "ibCommissionCurrency": "CHF",
        "buySell": "BUY",
        "levelOfDetail": "EXECUTION",
    }


def cash_tx(tx: str, on: date, kind: str, amount: str, currency: str = "CHF") -> dict[str, object]:
    return {
        "transactionID": tx,
        "type": kind,
        "currency": currency,
        "dateTime": d8(on),
        "settleDate": d8(on),
        "amount": amount,
        "description": f"{kind} fictif",
    }


def position(
    fund: tuple[str, str, str], qty: str, mark: str, value: str, currency: str = "USD"
) -> dict[str, object]:
    isin, symbol, name = fund
    return {
        "assetCategory": "STK",
        "symbol": symbol,
        "isin": isin,
        "description": name,
        "currency": currency,
        "position": qty,
        "markPrice": mark,
        "positionValue": value,
        "costBasisPrice": "100",
    }
