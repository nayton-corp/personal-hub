"""Collecteur « market » (lot 6) : cours de change, cours quotidiens et soldes crypto, par des
API publiques et sans identifiant bancaire.

- change : la BCE par Frankfurter (1 devise = x dans la devise de base `HUB_CURRENCY`,
  l'inverse du cours publié dans cette base) ;
- cryptos : CoinGecko, un an d'historique au premier run (limite de l'offre gratuite) ;
- titres cotés (facultatif) : le graphique quotidien de Yahoo Finance, pour les lignes qui
  n'ont pas d'autre source de cours (titres Revolut par exemple) ;
- portefeuilles : le solde des adresses publiques, lues dans les secrets de la
  connexion (champ `wallets`) : BTC par mempool.space (adresses, ou xpub d'un Ledger
  dont les adresses sont dérivées ici), ETH et ses jetons USDC/USDT par un nœud RPC public, SOL
  et ses jetons par le RPC public de Solana.

Tout est déposé dans un seul fichier `hub.market.v1` ; seul le domaine Finance le lit. Une source
facultative en panne n'empêche pas le dépôt du reste (le détail du run la nomme). Aucun calcul
en flottant : les nombres du JSON sont lus comme textes.
"""

from __future__ import annotations

import contextlib
import json
import re
import time
import urllib.parse
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation, localcontext
from typing import Any

from embit import bip32, script

from hub.collectors.base import Failure, Kind, Result
from hub.collectors.dropbox import is_market_json
from hub.collectors.http import Http
from hub.collectors.runtime import Env
from hub.core.money import base_currency

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


def fx_rates(
    env: Env, http: Http, since: date, *, latest: bool = False, until: date | None = None
) -> list[dict[str, str]]:
    m = env.cfg.market
    base = base_currency()
    # le franc reste suivi dans une autre base : un compte suisse (VIAC) est tenu en CHF
    symbols = ",".join(dict.fromkeys(c for c in [*m.currencies, "CHF"] if c != base))
    period = "latest" if latest else f"{since.isoformat()}..{until.isoformat() if until else ''}"
    query = urllib.parse.urlencode({"base": base, "symbols": symbols})
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
                inverse = Decimal(1) / rate
            out.append(
                {
                    "on_date": on_date[:10],
                    "base": ccy,
                    "quote": base,
                    "rate": text_of(inverse),
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
    base = base_currency()
    days = max(1, min(365, (env.today - since).days + 1))
    headers = {}
    key = env.creds.get("coingecko_key")
    if isinstance(key, str) and key:
        headers["x-cg-demo-api-key"] = key
    out = []
    for symbol, coin in sorted(m.crypto.items()):
        query = urllib.parse.urlencode(
            {"vs_currency": base.lower(), "days": days, "interval": "daily"}
        )
        url = f"{m.coingecko_url}/coins/{urllib.parse.quote(coin)}/market_chart?{query}"
        doc = http.json(url, f"crypto.{symbol.lower()}", headers=headers)
        series = _daily(doc.get("prices") if isinstance(doc, dict) else None)
        out += [
            {
                "instrument": symbol,
                "kind": "crypto",
                "on_date": on,
                "price": text_of(p),
                "currency": base,
                "source": "coingecko",
            }
            for on, p in sorted(series.items())
            if on >= since.isoformat()
        ]
    return out


def binance_prices(
    env: Env, http: Http, symbols: list[str], start: date, end: date
) -> list[dict[str, str]]:
    """Clôtures quotidiennes publiques de Binance (paire USDT, comptée en USD) : les cours d'avant
    la limite d'un an de CoinGecko, pour l'historique des portefeuilles."""
    day_ms = 86_400_000
    stop = int(datetime(end.year, end.month, end.day, tzinfo=UTC).timestamp()) * 1000
    out = []
    for symbol in symbols:
        cursor = int(datetime(start.year, start.month, start.day, tzinfo=UTC).timestamp()) * 1000
        for _page in range(20):
            query = urllib.parse.urlencode(
                {
                    "symbol": f"{symbol}USDT",
                    "interval": "1d",
                    "startTime": cursor,
                    "endTime": stop,
                    "limit": 1000,
                }
            )
            url = f"{env.cfg.market.binance_url}/api/v3/klines?{query}"
            rows = http.json(url, f"history.{symbol.lower()}")
            if not isinstance(rows, list) or not rows:
                break
            for r in rows:
                close = dec(r[4]) if isinstance(r, list) and len(r) > 4 else None
                if close is None or not isinstance(r[0], int):
                    continue
                on = datetime.fromtimestamp(r[0] // 1000, UTC).date().isoformat()
                out.append(
                    {
                        "instrument": symbol,
                        "kind": "crypto",
                        "on_date": on,
                        "price": text_of(close),
                        "currency": "USD",
                        "source": "binance",
                    }
                )
            cursor = int(rows[-1][0]) + day_ms
            if cursor >= stop:
                break
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


# mempool.space refuse (429) au-delà d'une vingtaine de requêtes rapprochées : une pause entre
# deux adresses, et une attente croissante avant de réessayer une requête refusée
RETRY_PAUSES = (10, 30, 60)
sleep: Callable[[int], None] = time.sleep


def _mempool(env: Env, http: Http, path: str, step: str = "wallet.btc") -> Any:
    url = f"{env.cfg.market.mempool_url}/address/{path}"
    for retry in (*RETRY_PAUSES, 0):
        if env.cfg.market.mempool_pause_seconds:
            sleep(env.cfg.market.mempool_pause_seconds)
        try:
            return http.json(url, step)
        except Failure as f:
            if not retry or not f.detail.endswith(":http_429"):
                raise
            sleep(retry)
    raise AssertionError  # pragma: no cover (la dernière tentative relève l'échec)


def _btc_address(env: Env, http: Http, address: str) -> tuple[Decimal, bool]:
    """(solde confirmé, adresse déjà utilisée) d'une adresse BTC."""
    doc = _mempool(env, http, urllib.parse.quote(address))
    try:
        stats = doc["chain_stats"]
        sats = int(stats["funded_txo_sum"]) - int(stats["spent_txo_sum"])
        txs = int(stats.get("tx_count", 0)) + int(
            (doc.get("mempool_stats") or {}).get("tx_count", 0)
        )
    except (KeyError, TypeError, ValueError, AttributeError):
        raise Failure("invalid_file", "wallet.btc") from None
    return Decimal(sats) / SATS, txs > 0 or int(stats["funded_txo_sum"]) > 0


# Scripts d'adresse d'une clé publique étendue ; une « xpub » ne dit pas lequel (Ledger Live
# donne une xpub même pour un compte Native SegWit), les quatre sont alors parcourus.
SCRIPTS: dict[str, Callable[[Any], Any]] = {
    "wpkh": script.p2wpkh,  # Native SegWit, bc1q… (BIP84)
    "sh-wpkh": lambda key: script.p2sh(script.p2wpkh(key)),  # SegWit, 3… (BIP49)
    "pkh": script.p2pkh,  # Legacy, 1… (BIP44)
    "tr": script.p2tr,  # Taproot, bc1p… (BIP86)
}
_PREFIX = {"zpub": ["wpkh"], "ypub": ["sh-wpkh"], "xpub": list(SCRIPTS)}


def xpub_key(xpub: str, chosen: str | None) -> tuple[Any, list[str]]:
    """Clé publique étendue et scripts à parcourir. Une clé privée est refusée."""
    kinds = [chosen] if chosen else _PREFIX.get(xpub[:4], [])
    if not kinds or any(k not in SCRIPTS for k in kinds):
        raise Failure("auth_error", "secret:wallets")
    try:
        key = bip32.HDKey.from_string(xpub)
    except Exception:  # embit lève des erreurs variées sur une clé mal formée
        raise Failure("auth_error", "secret:wallets") from None
    if key.is_private:
        raise Failure("auth_error", "secret:wallets")
    return key, kinds


def xpub_balance(
    env: Env, http: Http, xpub: str, chosen: str | None, seen_in: list[str] | None = None
) -> Decimal:
    """Somme des adresses de réception (0/i) et de monnaie (1/i), jusqu'à `gap_limit` adresses
    jamais utilisées de suite ; un script sans aucune réception utilisée est sauté. Les adresses
    utilisées sont ajoutées à `seen_in` (pour l'historique)."""
    key, kinds = xpub_key(xpub, chosen)
    gap_limit = env.cfg.market.gap_limit
    total = Decimal(0)
    for kind in kinds:
        for chain in (0, 1):
            branch = key.child(chain)
            index = gap = used = 0
            while gap < gap_limit:
                address = SCRIPTS[kind](branch.child(index).key).address()
                amount, seen = _btc_address(env, http, address)
                total += amount
                if seen and seen_in is not None:
                    seen_in.append(address)
                gap, used = (0, used + 1) if seen else (gap + 1, used)
                index += 1
            if chain == 0 and used == 0:
                break
    return total


def btc_wallet(env: Env, http: Http, w: dict[str, Any]) -> dict[str, Decimal]:
    """Solde BTC ; les adresses utilisées sont gardées dans `w["used"]` pour l'historique."""
    used = w.setdefault("used", [])
    total = Decimal(0)
    for a in w["addresses"]:
        amount, seen = _btc_address(env, http, a)
        total += amount
        if seen:
            used.append(a)
    for xpub in w["xpubs"]:
        total += xpub_balance(env, http, xpub, w.get("script"), used)
    return {"BTC": total}


TXS_PER_PAGE = 25  # mempool.space : transactions confirmées par page, des plus récentes
MAX_TX_PAGES = 40


def _txs(env: Env, http: Http, address: str, pages: int = MAX_TX_PAGES) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    path = f"{urllib.parse.quote(address)}/txs/chain"
    for _page in range(pages):
        page = _mempool(env, http, path, "history.btc")
        if not isinstance(page, list):
            raise Failure("invalid_file", "history.btc")
        out += page
        if len(page) < TXS_PER_PAGE:
            break
        path = (
            f"{urllib.parse.quote(address)}/txs/chain/{urllib.parse.quote(str(page[-1]['txid']))}"
        )
    return out


def btc_moves(
    env: Env, http: Http, addresses: list[str], pages: int = MAX_TX_PAGES
) -> list[tuple[str, str, int, int]]:
    """Transactions confirmées du portefeuille : (jour UTC, txid, net en sats, frais payés).
    Le net est ce qui arrive sur ces adresses moins ce qui en part (un virement entre deux
    adresses du portefeuille ne laisse que les frais) ; les frais ne comptent que si le
    portefeuille a payé (une de ses adresses en entrée)."""
    mine = set(addresses)
    txs: dict[str, dict[str, Any]] = {}
    for a in addresses:
        for tx in _txs(env, http, a, pages):
            txs[str(tx.get("txid"))] = tx
    out = []
    try:
        for txid, tx in txs.items():
            status = tx["status"]
            if not status.get("confirmed"):
                continue
            day = datetime.fromtimestamp(int(status["block_time"]), UTC).date().isoformat()
            received = sum(
                int(o["value"]) for o in tx["vout"] if o.get("scriptpubkey_address") in mine
            )
            spent = sum(
                int(i["prevout"]["value"])
                for i in tx["vin"]
                if (i.get("prevout") or {}).get("scriptpubkey_address") in mine
            )
            fee = int(tx.get("fee") or 0) if spent else 0
            out.append((day, txid, received - spent, fee))
    except (KeyError, TypeError, ValueError, AttributeError):
        raise Failure("invalid_file", "history.btc") from None
    return sorted(out)


def btc_history(moves: list[tuple[str, str, int, int]]) -> dict[str, Decimal]:
    """Solde BTC en fin de chaque jour (UTC) où il a bougé, depuis la première transaction."""
    by_day: dict[str, int] = {}
    for day, _txid, net, _fee in moves:
        by_day[day] = by_day.get(day, 0) + net
    balance, out = 0, {}
    for day in sorted(by_day):
        balance += by_day[day]
        out[day] = Decimal(max(balance, 0)) / SATS
    return out


def transactions(account: str, moves: list[tuple[str, str, int, int]]) -> list[dict[str, str]]:
    """Lignes `transactions` d'un compte BTC : une par transaction, net et frais en BTC."""
    return [
        {
            "account": account,
            "instrument": "BTC",
            "on_date": day,
            "txid": txid,
            "quantity": format((Decimal(net) / SATS).normalize(), "f"),
            "fee": format((Decimal(fee) / SATS).normalize(), "f"),
        }
        for day, txid, net, fee in moves
        if net or fee
    ]


def _rpc(url: str, http: Http, step: str, method: str, params: list[Any]) -> Any:
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    doc = http.json(url, step, method="POST", body=body)
    if not isinstance(doc, dict) or "result" not in doc:
        raise Failure("site_unavailable", f"{step}:rpc")
    return doc["result"]


def _scaled(raw: Any, places: int) -> Decimal:
    return Decimal(int(raw)) / (Decimal(10) ** places)


# nœud, Blockscout, crypto du gaz, contrat → symbole
Network = tuple[str, str, str, dict[str, str]]


def networks(env: Env, w: dict[str, Any]) -> list[Network]:
    """Réseaux lus pour un portefeuille ETH : Ethereum, et ceux qu'il nomme (`networks`)."""
    m = env.cfg.market
    out = []
    for name in w.get("networks") or ["ethereum"]:
        if name == "ethereum":
            tokens = {c: s for s, c in m.erc20_tokens.items()}
            out.append((m.eth_rpc_url, m.blockscout_url, "ETH", tokens))
        else:
            n = m.evm_networks[name]
            out.append((n.rpc_url, n.blockscout_url, n.native, dict(n.tokens)))
    return out


def _uint(url: str, http: Http, step: str, contract: str, data: str) -> int:
    return int(
        str(_rpc(url, http, step, "eth_call", [{"to": contract, "data": data}, "latest"])), 16
    )


def eth_wallet(env: Env, http: Http, w: dict[str, Any]) -> dict[str, Decimal]:
    out: dict[str, Decimal] = {}

    def add(symbol: str, amount: Decimal) -> None:
        out[symbol] = out.get(symbol, Decimal(0)) + amount

    try:
        for url, _scan, native, tokens in networks(env, w):
            for address in w["addresses"]:
                wei = int(
                    str(_rpc(url, http, "wallet.eth", "eth_getBalance", [address, "latest"])), 16
                )
                add(native, Decimal(wei) / WEI)
                owner = address[2:].lower().rjust(64, "0")
                for contract, symbol in sorted(tokens.items()):
                    held = _uint(url, http, "wallet.erc20", contract, "0x70a08231" + owner)
                    if held:  # balanceOf(adresse), puis decimals()
                        places = _uint(url, http, "wallet.erc20", contract, "0x313ce567")
                        add(symbol, _scaled(held, places))
                if url != env.cfg.market.eth_rpc_url:
                    continue
                for contract, symbol in sorted(env.cfg.market.staking_tokens.items()):
                    held = _uint(url, http, "wallet.staking", contract, "0x70a08231" + owner)
                    if held:
                        # balanceOfUnderlying(adresse) : la mise et ses récompenses
                        with contextlib.suppress(Failure):
                            held = _uint(
                                url, http, "wallet.staking", contract, "0x3af9e669" + owner
                            )
                        add(symbol, Decimal(held) / WEI)
    except (TypeError, ValueError):
        raise Failure("invalid_file", "wallet.eth") from None
    return out


SPL_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"


def sol_wallet(env: Env, http: Http, w: dict[str, Any]) -> dict[str, Decimal]:
    m = env.cfg.market
    out: dict[str, Decimal] = {}
    for address in w["addresses"]:
        try:
            lamports = _rpc(m.solana_rpc_url, http, "wallet.sol", "getBalance", [address])
            out["SOL"] = out.get("SOL", Decimal(0)) + _scaled(lamports["value"], 9)
            params = [address, {"programId": SPL_PROGRAM}, {"encoding": "jsonParsed"}]
            found = _rpc(m.solana_rpc_url, http, "wallet.spl", "getTokenAccountsByOwner", params)
            for item in found["value"]:
                info = item["account"]["data"]["parsed"]["info"]
                symbol = m.spl_tokens.get(str(info["mint"]))
                amount = info["tokenAmount"]
                if symbol and int(amount["amount"]):
                    held = _scaled(amount["amount"], int(amount["decimals"]))
                    out[symbol] = out.get(symbol, Decimal(0)) + held
        except (KeyError, TypeError, ValueError):
            raise Failure("invalid_file", "wallet.sol") from None
    return out


# --- historique ETH et SOL ---------------------------------------------------------------------

Move = tuple[str, str, str, Decimal, Decimal]  # jour UTC, txid, symbole, net (frais compris), frais
CHAIN_PAGES = 20  # pages de 100 (Blockscout) ou de 1000 signatures (Solana) au premier passage


def _blockscout(http: Http, url: str, action: str, address: str, page: int) -> list[Any]:
    query = urllib.parse.urlencode(
        {
            "module": "account",
            "action": action,
            "address": address,
            "sort": "desc",
            "page": page,
            "offset": 100,
        }
    )
    doc = http.json(f"{url}?{query}", "history.eth")
    rows = doc.get("result") if isinstance(doc, dict) else None
    if isinstance(rows, list):
        return rows
    if isinstance(doc, dict) and str(doc.get("message", "")).startswith("No "):
        return []  # « No transactions found »
    raise Failure("invalid_file", "history.eth")


def eth_moves(env: Env, http: Http, w: dict[str, Any], full: bool) -> list[Move]:
    """Transactions des adresses, sur chaque réseau du portefeuille (Blockscout) : crypto du
    gaz reçue ou envoyée (transactions et transferts internes), gaz payé, jetons suivis et
    jetons de staking (comptés comme la crypto mise en jeu). Au premier passage tout, ensuite
    la page la plus récente de chaque liste."""
    addresses = w["addresses"]
    mine = {a.lower() for a in addresses}
    staking = env.cfg.market.staking_tokens
    net: dict[tuple[str, str], Decimal] = {}
    fees: dict[str, tuple[str, Decimal]] = {}
    days: dict[str, str] = {}

    def add(txid: str, symbol: str, amount: Decimal, stamp: Any) -> None:
        days[txid] = datetime.fromtimestamp(int(stamp), UTC).date().isoformat()
        net[(txid, symbol)] = net.get((txid, symbol), Decimal(0)) + amount

    try:
        for _url, scan, native, tokens in networks(env, w):
            if scan == env.cfg.market.blockscout_url:
                tokens = {**tokens, **staking}
            tokens = {c.lower(): s for c, s in tokens.items()}
            for address in addresses:
                for action in ("txlist", "txlistinternal", "tokentx"):
                    for page in range(1, (CHAIN_PAGES if full else 1) + 1):
                        rows = _blockscout(http, scan, action, address, page)
                        for r in rows:
                            txid = str(r["hash"])
                            sender = str(r.get("from", "")).lower()
                            to = str(r.get("to", "")).lower()
                            if action == "tokentx":
                                symbol = tokens.get(str(r.get("contractAddress", "")).lower())
                                if symbol is None:
                                    continue  # jeton inconnu, souvent du spam
                                value = _scaled(r["value"], int(r["tokenDecimal"]))
                            else:
                                symbol = native
                                ok = str(r.get("isError", "0")) == "0"
                                value = Decimal(int(r["value"])) / WEI if ok else Decimal(0)
                                if action == "txlist" and sender in mine:
                                    gas = Decimal(int(r["gasUsed"]) * int(r["gasPrice"])) / WEI
                                    fees[txid] = (native, gas)
                                    add(txid, native, -gas, r["timeStamp"])
                            if to in mine:
                                add(txid, symbol, value, r["timeStamp"])
                            if sender in mine:
                                add(txid, symbol, -value, r["timeStamp"])
                        if len(rows) < 100:
                            break
    except (KeyError, TypeError, ValueError):
        raise Failure("invalid_file", "history.eth") from None
    out = []
    for (t, s), q in net.items():
        paid, fee = fees.get(t, ("", Decimal(0)))
        out.append((days[t], t, s, q, fee if s == paid else Decimal(0)))
    return sorted(out)


def sol_moves(env: Env, http: Http, w: dict[str, Any], full: bool) -> list[Move]:
    """Transactions des adresses Solana (nœud public) : SOL reçu ou envoyé, frais payés,
    jetons de `spl_tokens`."""
    addresses = w["addresses"]
    url, tokens = env.cfg.market.solana_rpc_url, env.cfg.market.spl_tokens
    out: list[Move] = []
    try:
        for address in addresses:
            signatures: list[dict[str, Any]] = []
            before = None
            for _page in range(CHAIN_PAGES if full else 1):
                options: dict[str, Any] = {"limit": 1000 if full else 25}
                if before:
                    options["before"] = before
                page = _rpc(url, http, "history.sol", "getSignaturesForAddress", [address, options])
                signatures += page
                if len(page) < options["limit"]:
                    break
                before = page[-1]["signature"]
            for sig in signatures:
                params = [
                    sig["signature"],
                    {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0},
                ]
                tx = _rpc(url, http, "history.sol", "getTransaction", params)
                if not tx or not tx.get("blockTime"):
                    continue
                day = datetime.fromtimestamp(int(tx["blockTime"]), UTC).date().isoformat()
                meta, keys = tx["meta"], tx["transaction"]["message"]["accountKeys"]
                pubkeys = [k["pubkey"] if isinstance(k, dict) else k for k in keys]
                txid = str(sig["signature"])
                if address in pubkeys:
                    i = pubkeys.index(address)
                    lamports = int(meta["postBalances"][i]) - int(meta["preBalances"][i])
                    fee = int(meta["fee"]) if i == 0 else 0
                    out.append((day, txid, "SOL", _scaled(lamports, 9), _scaled(fee, 9)))
                held: dict[str, Decimal] = {}
                for side, sign in (("preTokenBalances", -1), ("postTokenBalances", 1)):
                    for b in meta.get(side) or []:
                        symbol = tokens.get(str(b.get("mint")))
                        if symbol and b.get("owner") == address:
                            amount = b["uiTokenAmount"]
                            value = _scaled(amount["amount"], int(amount["decimals"]))
                            held[symbol] = held.get(symbol, Decimal(0)) + sign * value
                out += [(day, txid, s, q, Decimal(0)) for s, q in held.items()]
    except (KeyError, TypeError, ValueError, IndexError, AttributeError):
        raise Failure("invalid_file", "history.sol") from None
    return sorted(out)


# chaque crypto suivie en portefeuille a son historique (règle : pas de soldes sans écritures)
HISTORIES: dict[str, Callable[[Env, Http, dict[str, Any], bool], list[Move]]] = {
    "ETH": eth_moves,
    "SOL": sol_moves,
}


def chain_transactions(account: str, moves: list[Move]) -> list[dict[str, str]]:
    return [
        {
            "account": account,
            "instrument": symbol,
            "on_date": day,
            "txid": txid,
            "quantity": format(net.normalize(), "f"),
            "fee": format(fee.normalize(), "f"),
        }
        for day, txid, symbol, net, fee in moves
        if net or fee
    ]


WALLETS: dict[str, Callable[[Env, Http, dict[str, Any]], dict[str, Decimal]]] = {
    "BTC": btc_wallet,
    "ETH": eth_wallet,
    "SOL": sol_wallet,
}
_ACCOUNT = re.compile(r"^crypto:[a-z0-9][a-z0-9-]{0,40}$")


def wallet_entries(env: Env) -> list[dict[str, Any]]:
    """Portefeuilles de la connexion (réglages, et secrets d'avant G5), vérifiés avant tout
    appel : une erreur ici est `auth_error`."""
    legacy = env.creds.get("wallets") or []
    if not isinstance(legacy, list):
        raise Failure("auth_error", "secret:wallets")
    wallets = [*env.cfg.market.wallets, *legacy]
    out = []
    for w in wallets:
        if not isinstance(w, dict):
            raise Failure("auth_error", "secret:wallets")
        asset = str(w.get("asset") or "").upper()
        addresses = w.get("addresses") or []
        xpubs = w.get("xpubs") or ([w["xpub"]] if w.get("xpub") else [])
        if (
            asset not in WALLETS
            or not _ACCOUNT.match(str(w.get("account") or ""))
            or not isinstance(addresses, list)
            or not isinstance(xpubs, list)
            or not (addresses or xpubs)
            or (xpubs and asset != "BTC")
        ):
            raise Failure("auth_error", "secret:wallets")
        chains = w.get("networks") or []
        if asset == "ETH" and (
            not all(re.fullmatch(r"0x[0-9a-fA-F]{40}", str(a)) for a in addresses)
            or not isinstance(chains, list)
            or any(c != "ethereum" and c not in env.cfg.market.evm_networks for c in chains)
        ):
            raise Failure("auth_error", "secret:wallets")
        for x in xpubs:
            xpub_key(str(x), w.get("script"))
        out.append(
            {
                **w,
                "asset": asset,
                "addresses": [str(a) for a in addresses],
                "xpubs": [str(x) for x in xpubs],
            }
        )
    return out


def balances(
    env: Env, http: Http
) -> tuple[list[dict[str, str]], list[str], dict[str, str], list[dict[str, str]], dict[str, str]]:
    """(soldes, portefeuilles en échec, historiques relus : compte → premier jour, transactions).
    Un compte est relevé en entier ou pas du tout : un relevé partiel ferait disparaître une
    crypto de la valeur. Un compte vide donne un relevé à zéro.

    Au premier passage d'un compte BTC (mémoire `btc_history`), son historique est relu sur la
    chaîne et déposé en relevés passés, un par jour où le solde a bougé. Ses transactions
    partent dans le fichier : toutes au premier passage (mémoire `btc_txs`), ensuite la
    dernière page de chaque adresse (le registre écarte les doublons). Les comptes ETH et SOL
    font de même avec leurs transactions (mémoire `chain_txs`, `HISTORIES`)."""
    by_account: dict[str, list[dict[str, Any]]] = {}
    for w in wallet_entries(env):
        by_account.setdefault(str(w["account"]), []).append(w)
    out, failed, txs = [], [], []
    histories: dict[str, str] = {}
    done = set(env.memory.get("btc_history", []))
    listed = set(env.memory.get("btc_txs", []))
    chained = set(env.memory.get("chain_txs", []))
    chain_new: dict[str, str] = {}
    for account, entries in by_account.items():
        held: dict[str, Decimal] = {}
        try:
            for w in entries:
                for symbol, amount in WALLETS[w["asset"]](env, http, w).items():
                    held[symbol] = held.get(symbol, Decimal(0)) + amount
        except Failure as f:
            failed.append(f"wallet.{account.split(':', 1)[1]}:{f.outcome}")
            continue
        out += holdings(account, env.today, held, entries[0]["asset"])
        if any(w["asset"] != "BTC" for w in entries):
            full = account not in chained
            try:
                moves_of = [HISTORIES[w["asset"]](env, http, w, full) for w in entries]
            except Failure as f:
                failed.append(f"history.{account.split(':', 1)[1]}:{f.outcome}")
                continue
            found = [m for moves in moves_of for m in moves]
            txs += chain_transactions(account, found)
            if full:
                chain_new[account] = min((m[0] for m in found), default=env.today.isoformat())
            continue
        used = [a for w in entries for a in w.get("used", [])]
        full = account not in done or account not in listed
        try:
            moves = btc_moves(env, http, used, MAX_TX_PAGES if full else 1) if used else []
        except Failure as f:
            failed.append(f"history.{account.split(':', 1)[1]}:{f.outcome}")
            continue
        txs += transactions(account, moves)
        if full:
            histories[account] = min((d for d, *_x in moves), default=env.today.isoformat())
        if account in done:
            continue
        past = btc_history(moves)
        today = env.today.isoformat()
        for day, quantity in sorted(past.items()):
            if day < today:
                out += holdings(account, date.fromisoformat(day), {"BTC": quantity}, "BTC")
    return out, failed, histories, txs, chain_new


def holdings(account: str, on: date, held: dict[str, Decimal], empty: str) -> list[dict[str, str]]:
    """Lignes `balances` d'un compte : les cryptos détenues, ou une ligne à zéro s'il est vide."""
    rows = {s: q for s, q in held.items() if q > 0} or {empty: Decimal(0)}
    return [
        {
            "account": account,
            "instrument": symbol,
            "on_date": on.isoformat(),
            "quantity": format(quantity.normalize(), "f"),
        }
        for symbol, quantity in sorted(rows.items())
    ]


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
    sources: list[tuple[str, Callable[[], list[dict[str, str]]]]] = [
        ("crypto", lambda: crypto_prices(env, http, since)),
        ("quotes", lambda: quotes(env, http, since)),
    ]
    for name, fetch in sources:
        try:
            doc.setdefault("prices", []).extend(fetch())
        except Failure as f:
            failed.append(f"{name}:{f.outcome}")
    doc["balances"], down, histories, doc["transactions"], chains = balances(env, http)
    failed += down
    first = min([*histories.values(), *chains.values()], default=None)
    if first and first < since.isoformat():
        # l'historique remonte avant la fenêtre des cours : change BCE et clôtures Binance
        start = date.fromisoformat(first)
        symbols = sorted({"BTC"} if histories else set())
        symbols += sorted(
            {str(t["instrument"]) for t in doc["transactions"] if t["account"] in chains} - {"BTC"}
        )
        try:
            doc["fx"] += fx_rates(env, http, start, until=since)
            for symbol in symbols:
                try:
                    found = binance_prices(env, http, [symbol], start, since)
                except Failure as f:
                    if symbol == "BTC" or not f.detail.endswith(":http_400"):
                        raise
                    continue  # pas de paire USDT (USDT lui-même) : le dollar fait foi
                doc.setdefault("prices", []).extend(found)
        except Failure as f:
            failed.append(f"history_prices:{f.outcome}")
            histories, chains = {}, {}  # le prochain passage relit l'historique et ses cours
    data = json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()
    dropped = env.inbox.drop("market.json", data, is_market_json, step="market.file")
    if histories:
        env.memory.put("btc_history", sorted({*env.memory.get("btc_history", []), *histories}))
        env.memory.put("btc_txs", sorted({*env.memory.get("btc_txs", []), *histories}))
    if chains:
        env.memory.put("chain_txs", sorted({*env.memory.get("chain_txs", []), *chains}))
    if not failed:  # sinon le prochain run reprend la même fenêtre
        env.memory.put("last_run", env.today.isoformat())
    detail = "partial " + " ".join(failed) if failed else None
    return Result("ok" if dropped else "nothing_new", int(dropped), detail)
