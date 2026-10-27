"""Collecteur « market » (lot 6) : cours de change, cours quotidiens et soldes crypto, par des
API publiques et sans identifiant bancaire.

- change : la BCE par Frankfurter (1 devise = x CHF, l'inverse du cours publié en base CHF) ;
- cryptos : CoinGecko, un an d'historique au premier run (limite de l'offre gratuite) ;
- titres cotés (facultatif) : le graphique quotidien de Yahoo Finance, pour les lignes qui
  n'ont pas d'autre source de cours (titres Revolut par exemple) ;
- portefeuilles : le solde des adresses publiques (mempool.space pour BTC, un nœud RPC public
  pour ETH), adresses lues dans la section de secrets `collector-market` (champ `wallets`).

Tout est déposé dans un seul fichier `hub.market.v1` ; seul le domaine Finance le lit. Une source
facultative en panne n'empêche pas le dépôt du reste (le détail du run la nomme). Aucun calcul
en flottant : les nombres du JSON sont lus comme textes.
"""

from __future__ import annotations

import json
import urllib.parse
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation, localcontext
from typing import Any

from hub.collectors.base import Failure, Kind, Result
from hub.collectors.dropbox import is_market_json
from hub.collectors.http import Http
from hub.collectors.runtime import Env

OVERLAP_DAYS = 7
WEI = Decimal(10) ** 18
SATS = Decimal(10) ** 8


def dec(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        d = Decimal(str(value))
    except InvalidOperation:
        return None
    return d if d.is_finite() and d > 0 else None


def text_of(d: Decimal) -> str:
    with localcontext() as ctx:
        ctx.prec = 12
        out = +d
    return format(out.normalize(), "f")


def window(env: Env) -> date:
    """Premier jour à demander : un an au premier run, sinon une semaine de recouvrement."""
    last = env.memory.get("last_run")
    if last:
        return date.fromisoformat(last) - timedelta(days=OVERLAP_DAYS)
    return env.today - timedelta(days=env.cfg.market.backfill_days)


# --- change ------------------------------------------------------------------------------------


def fx_rates(env: Env, http: Http, since: date, *, latest: bool = False) -> list[dict[str, str]]:
    m = env.cfg.market
    symbols = ",".join(c for c in m.currencies if c != "CHF")
    period = "latest" if latest else f"{since.isoformat()}.."
    query = urllib.parse.urlencode({"base": "CHF", "symbols": symbols})
    doc = http.json(f"{m.fx_url}/{period}?{query}", "fx.rates")
    if not isinstance(doc, dict) or not isinstance(doc.get("rates"), dict):
        raise Failure("invalid_file", "fx.rates")
    days = doc["rates"] if not latest else {str(doc.get("date")): doc["rates"]}
    out = []
    for on_date, rates in sorted(days.items()):
        if not isinstance(rates, dict):
            continue
        for ccy, r in sorted(rates.items()):
            rate = dec(r)
            if rate is None:
                continue
            with localcontext() as ctx:
                ctx.prec = 28
                chf = Decimal(1) / rate
            out.append(
                {
                    "on_date": on_date[:10],
                    "base": ccy,
                    "quote": "CHF",
                    "rate": text_of(chf),
                    "source": "ecb",
                }
            )
    return out


# --- cryptos -----------------------------------------------------------------------------------


def _daily(points: Any) -> dict[str, Decimal]:
    """Dernier point de chaque jour (UTC) d'une série [[horodatage ms, valeur], ...]."""
    out: dict[str, Decimal] = {}
    for p in points if isinstance(points, list) else []:
        if not (isinstance(p, list) and len(p) == 2 and isinstance(p[0], int)):
            continue
        value = dec(p[1])
        if value is not None:
            on = datetime.fromtimestamp(p[0] / 1000, UTC).date().isoformat()
            out[on] = value
    return out


def crypto_prices(env: Env, http: Http, since: date) -> list[dict[str, str]]:
    m = env.cfg.market
    days = max(1, min(365, (env.today - since).days + 1))
    headers = {}
    key = env.creds.get("coingecko_key")
    if isinstance(key, str) and key:
        headers["x-cg-demo-api-key"] = key
    out = []
    for symbol, coin in sorted(m.crypto.items()):
        query = urllib.parse.urlencode({"vs_currency": "chf", "days": days, "interval": "daily"})
        url = f"{m.coingecko_url}/coins/{urllib.parse.quote(coin)}/market_chart?{query}"
        doc = http.json(url, f"crypto.{symbol.lower()}", headers=headers)
        series = _daily(doc.get("prices") if isinstance(doc, dict) else None)
        out += [
            {
                "instrument": symbol,
                "kind": "crypto",
                "on_date": on,
                "price": text_of(p),
                "currency": "CHF",
                "source": "coingecko",
            }
            for on, p in sorted(series.items())
            if on >= since.isoformat()
        ]
    return out


# --- titres cotés ------------------------------------------------------------------------------


def quotes(env: Env, http: Http, since: date) -> list[dict[str, str]]:
    m = env.cfg.market
    rng = "1y" if (env.today - since).days > 31 else "1mo"
    out = []
    for instrument, ticker in sorted(m.quotes.items()):
        query = urllib.parse.urlencode({"range": rng, "interval": "1d"})
        url = f"{m.yahoo_url}/{urllib.parse.quote(ticker)}?{query}"
        doc = http.json(url, f"quote.{instrument.lower()}")
        try:
            result = doc["chart"]["result"][0]
            currency = str(result["meta"]["currency"])
            stamps = result["timestamp"]
            closes = result["indicators"]["quote"][0]["close"]
        except (KeyError, IndexError, TypeError):
            raise Failure("invalid_file", f"quote.{instrument.lower()}") from None
        scale = Decimal(1)
        if currency in ("GBp", "GBX"):  # cotation en pence
            currency, scale = "GBP", Decimal(100)
        kind = "fund" if instrument.upper().startswith(("IE", "LU")) else "stock"
        series: dict[str, Decimal] = {}
        for ts, close in zip(stamps, closes, strict=False):
            value = dec(close)
            if isinstance(ts, int) and value is not None:
                series[datetime.fromtimestamp(ts, UTC).date().isoformat()] = value / scale
        out += [
            {
                "instrument": instrument,
                "kind": kind,
                "on_date": on,
                "price": text_of(p),
                "currency": currency.upper(),
                "source": "yahoo",
            }
            for on, p in sorted(series.items())
            if on >= since.isoformat()
        ]
    return out


# --- portefeuilles -----------------------------------------------------------------------------


def btc_balance(env: Env, http: Http, address: str) -> Decimal:
    doc = http.json(
        f"{env.cfg.market.mempool_url}/address/{urllib.parse.quote(address)}", "wallet.btc"
    )
    try:
        stats = doc["chain_stats"]
        sats = int(stats["funded_txo_sum"]) - int(stats["spent_txo_sum"])
    except (KeyError, TypeError, ValueError):
        raise Failure("invalid_file", "wallet.btc") from None
    return Decimal(sats) / SATS


def eth_balance(env: Env, http: Http, address: str) -> Decimal:
    body = {"jsonrpc": "2.0", "id": 1, "method": "eth_getBalance", "params": [address, "latest"]}
    doc = http.json(env.cfg.market.eth_rpc_url, "wallet.eth", method="POST", body=body)
    try:
        wei = int(str(doc["result"]), 16)
    except (KeyError, TypeError, ValueError):
        raise Failure("invalid_file", "wallet.eth") from None
    return Decimal(wei) / WEI


BALANCES = {"BTC": btc_balance, "ETH": eth_balance}


def balances(env: Env, http: Http) -> list[dict[str, str]]:
    wallets = env.creds.get("wallets") or []
    if not isinstance(wallets, list):
        raise Failure("auth_error", "secret:wallets")
    out = []
    for w in wallets:
        if not isinstance(w, dict):
            raise Failure("auth_error", "secret:wallets")
        asset = str(w.get("asset") or "").upper()
        reader = BALANCES.get(asset)
        addresses = w.get("addresses") or []
        if reader is None or not isinstance(addresses, list) or not w.get("account"):
            raise Failure("auth_error", "secret:wallets")
        total = sum((reader(env, http, str(a)) for a in addresses), Decimal(0))
        out.append(
            {
                "account": str(w["account"]),
                "instrument": asset,
                "on_date": env.today.isoformat(),
                "quantity": format(total.normalize(), "f"),
            }
        )
    return out


# --- run ---------------------------------------------------------------------------------------


def run(env: Env, kind: Kind, http: Http | None = None) -> Result:
    http = http or Http()
    since = window(env)
    if kind == "check":
        fx_rates(env, http, since, latest=True)
        return Result("ok")
    doc: dict[str, Any] = {
        "format": "hub.market.v1",
        "fetched_at": env.today.isoformat(),
        "fx": fx_rates(env, http, since),
    }
    failed = []
    sources: list[tuple[str, str, Callable[[], list[dict[str, str]]]]] = [
        ("crypto", "prices", lambda: crypto_prices(env, http, since)),
        ("quotes", "prices", lambda: quotes(env, http, since)),
        ("wallets", "balances", lambda: balances(env, http)),
    ]
    for name, part, fetch in sources:
        try:
            doc.setdefault(part, []).extend(fetch())
        except Failure as f:
            if f.outcome == "auth_error" and name == "wallets":
                raise
            failed.append(f"{name}:{f.outcome}")
    data = json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()
    dropped = env.inbox.drop("market.json", data, is_market_json, step="market.file")
    if not failed:  # sinon le prochain run reprend la même fenêtre
        env.memory.put("last_run", env.today.isoformat())
    detail = "partial " + " ".join(failed) if failed else None
    return Result("ok" if dropped else "nothing_new", int(dropped), detail)
