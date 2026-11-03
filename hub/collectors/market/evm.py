"""Réseaux compatibles Ethereum d'un portefeuille : nœud public pour le solde, et l'API
d'historique compatible Etherscan de chacun : Routescan pour Ethereum (sans clé), Etherscan V2
avec la clé pour les autres, ou l'explorateur sans clé d'un réseau hors de son offre gratuite."""

from __future__ import annotations

from typing import Any, NamedTuple

from hub.collectors.runtime import Env


class Network(NamedTuple):
    name: str
    rpc: str
    native: str  # crypto qui paie le gaz
    tokens: dict[str, str]  # contrat → symbole
    scan: str  # API d'historique compatible Etherscan
    params: dict[str, str]  # paramètres en plus (réseau, clé) ; `None` : clé manquante


def networks(env: Env, w: dict[str, Any]) -> list[Network]:
    """Réseaux lus pour un portefeuille ETH : Ethereum, et ceux qu'il nomme (`networks`)."""
    m, key = env.cfg.market, env.creds.get("etherscan_key")
    keyed = isinstance(key, str) and bool(key)
    out = []
    for name in w.get("networks") or ["ethereum"]:
        if name == "ethereum":  # Routescan, sans clé
            rpc, native, chain_id, own = m.eth_rpc_url, "ETH", 1, m.eth_history_url
            tokens = {c: s for s, c in m.erc20_tokens.items()}
        else:
            n = m.evm_networks[name]
            rpc, native, chain_id, own, tokens = (
                n.rpc_url,
                n.native,
                n.chain_id,
                n.history_url,
                n.tokens,
            )
        params = {"chainid": str(chain_id), "apikey": str(key)} if keyed and not own else {}
        out.append(Network(name, rpc, native, dict(tokens), own or m.etherscan_url, params))
    return out
