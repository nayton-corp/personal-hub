"""Historiques sur chaîne des portefeuilles suivis (règle : pas de soldes sans écritures) :
BTC (mempool.space), EVM (explorateurs Etherscan/Blockscout), Solana (nœud public) ; ATOM vit
dans `cosmos`, EGLD dans `multiversx`. Chaque lecture page par page dit quand l'historique
continue au-delà des pages lues (`truncated`, audit M8) : le passage est alors « incomplet »
et relit tout la fois d'après.
"""

from __future__ import annotations

import urllib.parse
from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from hub.collectors.base import Failure
from hub.collectors.http import Http
from hub.collectors.market.cosmos import atom_moves
from hub.collectors.market.evm import Network, networks
from hub.collectors.market.multiversx import egld_moves
from hub.collectors.market.net import SATS, WEI, mempool, polite, rpc, scaled
from hub.collectors.runtime import Env

TXS_PER_PAGE = 25  # mempool.space : transactions confirmées par page, des plus récentes
MAX_TX_PAGES = 40


def _txs(
    env: Env, http: Http, address: str, pages: int = MAX_TX_PAGES
) -> tuple[list[dict[str, Any]], bool]:
    """Les transactions d'une adresse, page par page, et vrai si la dernière page lue était
    pleine : l'historique continue au-delà de ce que le passage a lu (audit M8)."""
    out: list[dict[str, Any]] = []
    path = f"{urllib.parse.quote(address)}/txs/chain"
    for _page in range(pages):
        page = mempool(env, http, path, "history.btc")
        if not isinstance(page, list):
            raise Failure("invalid_file", "history.btc")
        out += page
        if len(page) < TXS_PER_PAGE:
            return out, False
        path = (
            f"{urllib.parse.quote(address)}/txs/chain/{urllib.parse.quote(str(page[-1]['txid']))}"
        )
    return out, True


def btc_moves(
    env: Env, http: Http, addresses: list[str], pages: int = MAX_TX_PAGES
) -> tuple[list[tuple[str, str, int, int]], bool]:
    """Transactions confirmées du portefeuille : (jour UTC, txid, net en sats, frais payés), et
    vrai si une adresse a plus de transactions que le passage n'en a lu.
    Le net est ce qui arrive sur ces adresses moins ce qui en part (un virement entre deux
    adresses du portefeuille ne laisse que les frais) ; les frais ne comptent que si le
    portefeuille a payé (une de ses adresses en entrée)."""
    mine = set(addresses)
    txs: dict[str, dict[str, Any]] = {}
    truncated = False
    for a in addresses:
        found, cut = _txs(env, http, a, pages)
        truncated = truncated or cut
        for tx in found:
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
    return sorted(out), truncated


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


Move = tuple[str, str, str, Decimal, Decimal, str]
CHAIN_PAGES = 20  # pages de 100 (Blockscout) ou de 1000 signatures (Solana) au premier passage
BLOCKED_DAYS = 7  # un explorateur qui refuse l'accès est redemandé une fois par semaine
REFUSED = ("http_401", "http_403")


def _blocked(env: Env, label: str) -> bool:
    """Ce réseau a été refusé par son explorateur sans clé il y a moins d'une semaine (mémoire
    `chain_blocked`) : inutile de le redemander à chaque passage, le solde reste lu."""
    since = env.memory.get("chain_blocked", {}).get(label)
    return isinstance(since, str) and (env.today - date.fromisoformat(since)).days < BLOCKED_DAYS


def _block(env: Env, label: str, blocked: bool) -> None:
    known = dict(env.memory.get("chain_blocked", {}))
    if blocked:
        known[label] = env.today.isoformat()
    elif known.pop(label, None) is None:
        return
    env.memory.put("chain_blocked", known)


def _scan(env: Env, http: Http, net: Network, action: str, address: str, page: int) -> list[Any]:
    query = urllib.parse.urlencode(
        {
            **net.params,
            "module": "account",
            "action": action,
            "address": address,
            "sort": "desc",
            "page": page,
            "offset": 100,
        }
    )

    def rows_of(doc: Any) -> list[Any]:
        rows = doc.get("result") if isinstance(doc, dict) else None
        if isinstance(rows, list):
            return rows
        said = f"{doc.get('message', '')} {rows}".lower() if isinstance(doc, dict) else ""
        if said.startswith("no "):
            return []  # « No transactions found »
        if "rate limit" in said:
            raise Failure("site_unavailable", "history.eth:http_429")  # réessayé
        if "api key" in said:
            raise Failure("auth_error", "history.eth:key")
        if "not supported" in said:
            raise Failure("site_unavailable", "history.eth:unsupported")
        raise Failure("invalid_file", "history.eth")

    step = f"history.{net.name}"
    return polite(http, f"{net.scan}?{query}", step, env.cfg.market.chain_pause_seconds, rows_of)  # type: ignore[no-any-return]


def eth_moves(
    env: Env, http: Http, w: dict[str, Any], chained: set[str]
) -> tuple[list[Move], dict[str, str], list[str]]:
    """Transactions des adresses, sur chaque réseau du portefeuille : crypto du gaz reçue ou
    envoyée (transactions et transferts internes), gaz payé, jetons suivis et jetons de
    staking (comptés comme la crypto mise en jeu). Chaque réseau est relu en entier la
    première fois (mémoire `chain_txs` : `<compte>` pour Ethereum, `<compte>@<réseau>`
    sinon), ensuite la page la plus récente de chaque liste. Un réseau sans clé Etherscan est
    signalé (`needs_key`) et relu en entier quand elle arrive ; un explorateur sans clé qui
    refuse l'accès (403) l'est aussi (`blocked`) : solde seul, nouvel essai chaque semaine.
    Rend (transactions, réseaux relus en entier → premier jour, à signaler)."""
    account, addresses = str(w["account"]), w["addresses"]
    mine = {a.lower() for a in addresses}
    staking = env.cfg.market.staking_tokens
    staked: set[str] = set()  # transactions qui touchent un staking
    pools = {c.lower() for c in staking}
    net: dict[tuple[str, str], Decimal] = {}
    fees: dict[str, tuple[str, Decimal]] = {}
    days: dict[str, str] = {}
    first: dict[str, str] = {}
    notes: list[str] = []
    cut: set[str] = set()  # réseaux dont une adresse dépasse les pages lues

    def add(txid: str, symbol: str, amount: Decimal, stamp: Any) -> None:
        days[txid] = datetime.fromtimestamp(int(stamp), UTC).date().isoformat()
        net[(txid, symbol)] = net.get((txid, symbol), Decimal(0)) + amount

    wallet = account.split(":", 1)[1]
    try:
        for network in networks(env, w):
            label = account if network.name == "ethereum" else f"{account}@{network.name}"
            if network.scan == env.cfg.market.etherscan_url and not network.params:
                notes.append(f"history.{wallet}.{network.name}:needs_key")
                continue
            if _blocked(env, label):
                notes.append(f"history.{wallet}.{network.name}:blocked")
                continue
            full = label not in chained
            tokens = {**network.tokens, **staking} if network.name == "ethereum" else network.tokens
            tokens = {c.lower(): s for c, s in tokens.items()}
            native = network.native
            before = (set(days), set(net), set(fees))  # un réseau en erreur est retiré en entier
            try:
                for address in addresses:
                    for action in ("txlist", "txlistinternal", "tokentx"):
                        for page in range(1, (CHAIN_PAGES if full else 1) + 1):
                            try:
                                rows = _scan(env, http, network, action, address, page)
                            except Failure as f:
                                # Polygon : l'offre gratuite refuse les transferts internes en
                                # disant « Invalid API Key » ; un écart éventuel se voit au
                                # rapprochement
                                if action != "txlistinternal" or not f.detail.endswith(":key"):
                                    raise
                                break
                            for r in rows:
                                txid = str(r["hash"])
                                sender = str(r.get("from", "")).lower()
                                to = str(r.get("to", "")).lower()
                                if action == "txlistinternal" and r.get("type", "call") != "call":
                                    continue  # delegatecall, staticcall : aucun ETH ne bouge
                                if pools & {sender, to, str(r.get("contractAddress", "")).lower()}:
                                    staked.add(txid)
                                if action == "tokentx":
                                    symbol = tokens.get(str(r.get("contractAddress", "")).lower())
                                    if symbol is None:
                                        continue  # jeton inconnu, souvent du spam
                                    value = scaled(r["value"], int(r["tokenDecimal"]))
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
                        else:  # toutes les pages pleines : la chaîne continue au-delà
                            cut.add(network.name)
            except Failure as f:
                # un réseau en erreur est signalé avec sa cause ; les autres continuent
                cause = f.detail.rpartition(":")[2] if ":" in f.detail else f.outcome
                if cause in REFUSED:  # avec une clé, c'est elle ; sans, l'explorateur est fermé
                    cause = "key" if network.params else "blocked"
                    _block(env, label, cause == "blocked")
                notes.append(f"history.{wallet}.{network.name}:{cause}")
                for k in set(days) - before[0]:
                    del days[k]
                for kn in set(net) - before[1]:
                    del net[kn]
                for k in set(fees) - before[2]:
                    del fees[k]
                continue
            _block(env, label, False)
            if network.name in cut:  # dit, et relu en entier au prochain passage (audit M8)
                notes.append(f"history.{wallet}.{network.name}:truncated")
            elif full:
                found = [v for k, v in days.items() if k not in before[0]]
                first[label] = min(found, default=env.today.isoformat())
    except (KeyError, TypeError, ValueError):
        raise Failure("invalid_file", "history.eth") from None
    out = []
    for (t, s), q in net.items():
        paid, fee = fees.get(t, ("", Decimal(0)))
        stake = "stake" if t in staked else ""
        out.append((days[t], t, s, q, fee if s == paid else Decimal(0), stake))
    return sorted(out), first, notes


def sol_moves(
    env: Env, http: Http, w: dict[str, Any], chained: set[str]
) -> tuple[list[Move], dict[str, str], list[str]]:
    """Transactions des adresses Solana (nœud public) : SOL reçu ou envoyé, frais payés,
    jetons de `spl_tokens`. Tout la première fois (mémoire `chain_txs` : `<compte>@solana`)."""
    addresses = w["addresses"]
    label = f"{w['account']}@solana"
    full = label not in chained
    truncated = False
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
                page = rpc(url, http, "history.sol", "getSignaturesForAddress", [address, options])
                signatures += page
                if len(page) < options["limit"]:
                    break
                before = page[-1]["signature"]
            else:  # toutes les pages pleines : l'historique continue au-delà (audit M8)
                truncated = True
            for sig in signatures:
                params = [
                    sig["signature"],
                    {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0},
                ]
                tx = rpc(url, http, "history.sol", "getTransaction", params)
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
                    out.append((day, txid, "SOL", scaled(lamports, 9), scaled(fee, 9), ""))
                held: dict[str, Decimal] = {}
                for side, sign in (("preTokenBalances", -1), ("postTokenBalances", 1)):
                    for b in meta.get(side) or []:
                        symbol = tokens.get(str(b.get("mint")))
                        if symbol and b.get("owner") == address:
                            amount = b["uiTokenAmount"]
                            value = scaled(amount["amount"], int(amount["decimals"]))
                            held[symbol] = held.get(symbol, Decimal(0)) + sign * value
                out += [(day, txid, s, q, Decimal(0), "") for s, q in held.items()]
    except (KeyError, TypeError, ValueError, IndexError, AttributeError):
        raise Failure("invalid_file", "history.sol") from None
    if truncated:  # dit, et relu en entier au prochain passage
        return sorted(out), {}, [f"history.{w['account'].split(':', 1)[1]}.solana:truncated"]
    first = {label: min((m[0] for m in out), default=env.today.isoformat())}
    return sorted(out), first if full else {}, []


# chaque crypto suivie en portefeuille a son historique (règle : pas de soldes sans écritures)
History = Callable[
    [Env, Http, dict[str, Any], set[str]], tuple[list[Move], dict[str, str], list[str]]
]
HISTORIES: dict[str, History] = {
    "ETH": eth_moves,
    "SOL": sol_moves,
    "ATOM": atom_moves,
    "EGLD": egld_moves,
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
            **({"kind": kind} if kind else {}),
        }
        for day, txid, symbol, net, fee, kind in moves
        if net or fee
    ]
