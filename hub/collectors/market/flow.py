"""Collecteur « market » (lot 6) : cours de change, cours quotidiens et soldes crypto, par des
API publiques et sans identifiant bancaire.

- change : la BCE par Frankfurter (1 devise = x CHF, l'inverse du cours publié en base CHF) ;
- cryptos : CoinGecko, un an d'historique au premier run (limite de l'offre gratuite) ;
- titres cotés (facultatif) : le graphique quotidien de Yahoo Finance, pour les lignes qui
  n'ont pas d'autre source de cours (titres Revolut par exemple) ;
- portefeuilles : le solde des adresses publiques, lues dans la section de secrets
  `collector-market` (champ `wallets`) : BTC par mempool.space (adresses, ou xpub d'un Ledger
  dont les adresses sont dérivées ici), ETH et ses jetons USDC/USDT par un nœud RPC public, SOL
  et ses jetons par le RPC public de Solana.

Tout est déposé dans un seul fichier `hub.market.v1` ; seul le domaine Finance le lit. Une source
facultative en panne n'empêche pas le dépôt du reste (le détail du run la nomme). Aucun calcul
en flottant : les nombres du JSON sont lus comme textes.
"""

from __future__ import annotations

import json
import re
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


def _btc_address(env: Env, http: Http, address: str) -> tuple[Decimal, bool]:
    """(solde confirmé, adresse déjà utilisée) d'une adresse BTC."""
    doc = http.json(
        f"{env.cfg.market.mempool_url}/address/{urllib.parse.quote(address)}", "wallet.btc"
    )
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


def xpub_balance(env: Env, http: Http, xpub: str, chosen: str | None) -> Decimal:
    """Somme des adresses de réception (0/i) et de monnaie (1/i), jusqu'à `gap_limit` adresses
    jamais utilisées de suite ; un script sans aucune réception utilisée est sauté."""
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
                gap, used = (0, used + 1) if seen else (gap + 1, used)
                index += 1
            if chain == 0 and used == 0:
                break
    return total


def btc_wallet(env: Env, http: Http, w: dict[str, Any]) -> dict[str, Decimal]:
    total = sum((_btc_address(env, http, str(a))[0] for a in w["addresses"]), Decimal(0))
    for xpub in w["xpubs"]:
        total += xpub_balance(env, http, xpub, w.get("script"))
    return {"BTC": total}


def _rpc(url: str, http: Http, step: str, method: str, params: list[Any]) -> Any:
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    doc = http.json(url, step, method="POST", body=body)
    if not isinstance(doc, dict) or "result" not in doc:
        raise Failure("site_unavailable", f"{step}:rpc")
    return doc["result"]


def _scaled(raw: Any, places: int) -> Decimal:
    return Decimal(int(raw)) / (Decimal(10) ** places)


def eth_wallet(env: Env, http: Http, w: dict[str, Any]) -> dict[str, Decimal]:
    url = env.cfg.market.eth_rpc_url
    out: dict[str, Decimal] = {}
    for address in w["addresses"]:
        try:
            wei = int(str(_rpc(url, http, "wallet.eth", "eth_getBalance", [address, "latest"])), 16)
            out["ETH"] = out.get("ETH", Decimal(0)) + Decimal(wei) / WEI
            owner = "0x70a08231" + address[2:].lower().rjust(64, "0")  # balanceOf(adresse)
            for symbol, contract in sorted(env.cfg.market.erc20_tokens.items()):
                call = [{"to": contract, "data": owner}, "latest"]
                held = int(str(_rpc(url, http, "wallet.erc20", "eth_call", call)), 16)
                if held:
                    call = [{"to": contract, "data": "0x313ce567"}, "latest"]  # decimals()
                    places = int(str(_rpc(url, http, "wallet.erc20", "eth_call", call)), 16)
                    out[symbol] = out.get(symbol, Decimal(0)) + _scaled(held, places)
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


WALLETS: dict[str, Callable[[Env, Http, dict[str, Any]], dict[str, Decimal]]] = {
    "BTC": btc_wallet,
    "ETH": eth_wallet,
    "SOL": sol_wallet,
}
_ACCOUNT = re.compile(r"^crypto:[a-z0-9][a-z0-9-]{0,40}$")


def wallet_entries(env: Env) -> list[dict[str, Any]]:
    """Portefeuilles des secrets, vérifiés avant tout appel : une erreur ici est `auth_error`."""
    wallets = env.creds.get("wallets") or []
    if not isinstance(wallets, list):
        raise Failure("auth_error", "secret:wallets")
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
        if asset == "ETH" and not all(
            re.fullmatch(r"0x[0-9a-fA-F]{40}", str(a)) for a in addresses
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


def balances(env: Env, http: Http) -> tuple[list[dict[str, str]], list[str]]:
    """(soldes, portefeuilles en échec). Un compte est relevé en entier ou pas du tout : un relevé
    partiel ferait disparaître une crypto de la valeur. Un compte vide donne un relevé à zéro."""
    by_account: dict[str, list[dict[str, Any]]] = {}
    for w in wallet_entries(env):
        by_account.setdefault(str(w["account"]), []).append(w)
    out, failed = [], []
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
    return out, failed


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
    doc["balances"], down = balances(env, http)  # des secrets illisibles : auth_error
    failed += down
    data = json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()
    dropped = env.inbox.drop("market.json", data, is_market_json, step="market.file")
    if not failed:  # sinon le prochain run reprend la même fenêtre
        env.memory.put("last_run", env.today.isoformat())
    detail = "partial " + " ".join(failed) if failed else None
    return Result("ok" if dropped else "nothing_new", int(dropped), detail)
