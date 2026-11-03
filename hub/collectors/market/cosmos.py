"""Cosmos Hub (ATOM) : solde (disponible, mis en jeu, en retrait, récompenses) et historique
par le REST public d'un nœud Cosmos."""

from __future__ import annotations

import urllib.parse
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from hub.collectors.base import Failure
from hub.collectors.http import Http
from hub.collectors.runtime import Env

if TYPE_CHECKING:
    from hub.collectors.market.flow import Move

UATOM = Decimal(10) ** 6
PAGES = 20  # pages de 100 transactions au premier passage, comme les autres historiques


def _cosmos(env: Env, http: Http, path: str, step: str) -> Any:
    from hub.collectors.market import flow  # la pause et ses reprises, partagées

    url = f"{env.cfg.market.cosmos_rest_url}{path}"
    return flow.polite(http, url, step, env.cfg.market.chain_pause_seconds)


def _uatom(coins: Any) -> Decimal:
    """Somme des montants en uatom d'une liste de pièces (`{denom, amount}`)."""
    return (
        sum(
            (Decimal(str(c["amount"])) for c in coins or [] if c.get("denom") == "uatom"),
            Decimal(0),
        )
        / UATOM
    )


def atom_wallet(env: Env, http: Http, w: dict[str, Any]) -> dict[str, Decimal]:
    """ATOM disponible, mis en jeu, en cours de retrait et récompenses à réclamer : tout compte,
    comme un ETH mis en jeu chez Kiln."""
    total = Decimal(0)
    try:
        for a in w["addresses"]:
            bank = _cosmos(env, http, f"/cosmos/bank/v1beta1/balances/{a}", "wallet.atom")
            total += _uatom(bank["balances"])
            staked = _cosmos(env, http, f"/cosmos/staking/v1beta1/delegations/{a}", "wallet.atom")
            total += _uatom(d["balance"] for d in staked["delegation_responses"])
            path = f"/cosmos/staking/v1beta1/delegators/{a}/unbonding_delegations"
            leaving = _cosmos(env, http, path, "wallet.atom")
            total += sum(
                (
                    Decimal(str(e["balance"])) / UATOM
                    for u in leaving["unbonding_responses"]
                    for e in u["entries"]
                ),
                Decimal(0),
            )
            path = f"/cosmos/distribution/v1beta1/delegators/{a}/rewards"
            total += _uatom(_cosmos(env, http, path, "wallet.atom")["total"])
    except (KeyError, TypeError, ValueError, ArithmeticError):
        raise Failure("invalid_file", "wallet.atom") from None
    return {"ATOM": total} if total else {}


def atom_moves(
    env: Env, http: Http, w: dict[str, Any], chained: set[str]
) -> tuple[list[Move], dict[str, str], list[str]]:
    """Transactions Cosmos de l'adresse (envoyées et reçues) : variation d'ATOM lue dans les
    événements `coin_received` et `coin_spent`, frais payés compris. Une mise en jeu y est un
    envoi vers le module de staking, un retrait de récompenses une arrivée. Tout la première
    fois (mémoire `<compte>@cosmos`), ensuite la page la plus récente."""
    label = f"{w['account']}@cosmos"
    full = label not in chained
    out: dict[str, tuple[str, Decimal, Decimal]] = {}
    try:
        for a in w["addresses"]:
            for query in (f"message.sender='{a}'", f"transfer.recipient='{a}'"):
                for page in range(1, (PAGES if full else 1) + 1):
                    params = urllib.parse.urlencode(
                        {
                            "query": query,
                            "pagination.limit": 100,
                            "pagination.offset": (page - 1) * 100,
                            "order_by": "ORDER_BY_DESC",
                        }
                    )
                    doc = _cosmos(env, http, f"/cosmos/tx/v1beta1/txs?{params}", "history.atom")
                    rows = doc.get("tx_responses") or []
                    txs = doc.get("txs") or []
                    for i, r in enumerate(rows):
                        txid = str(r["txhash"])
                        if txid in out or str(r.get("code", 0)) != "0":
                            continue
                        net = Decimal(0)
                        for e in r.get("events") or []:
                            attrs = {x.get("key"): x.get("value") for x in e.get("attributes", [])}
                            who = attrs.get("receiver") or attrs.get("spender")
                            if who != a or e.get("type") not in ("coin_received", "coin_spent"):
                                continue
                            sign = 1 if e["type"] == "coin_received" else -1
                            for part in str(attrs.get("amount") or "").split(","):
                                if part.endswith("uatom"):
                                    net += sign * Decimal(part[: -len("uatom")]) / UATOM
                        fee = Decimal(0)
                        tx = txs[i] if i < len(txs) else {}
                        if query.startswith("message.sender"):  # l'émetteur paie les frais
                            fee = _uatom(
                                ((tx.get("auth_info") or {}).get("fee") or {}).get("amount")
                            )
                        day = str(r["timestamp"])[:10]
                        if net or fee:
                            out[txid] = (day, net, fee)
                    if len(rows) < 100:
                        break
    except (KeyError, TypeError, ValueError, ArithmeticError):
        raise Failure("invalid_file", "history.atom") from None
    moves = sorted((d, t, "ATOM", n, f, "") for t, (d, n, f) in out.items())
    if full and not moves:
        # les nœuds publics élaguent leur index : aucune transaction n'y est trouvée, ce qui
        # est signalé (et relu au passage suivant) plutôt que pris pour un compte sans histoire
        return [], {}, [f"history.{str(w['account']).split(':', 1)[1]}.cosmos:pruned"]
    first = {label: min((m[0] for m in moves), default=env.today.isoformat())}
    return moves, first if full else {}, []
