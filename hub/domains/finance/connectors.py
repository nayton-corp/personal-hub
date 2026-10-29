"""Les sources de la finance (chantier S1) : le catalogue des connecteurs, déclaré au cœur par
le point d'entrée `hub.connectors`, et les modules ouverts par pays (`hub.country_modules`).

Le cœur ne connaît ni banque ni portefeuille : il valide une connexion avec ce que ce catalogue
déclare (secrets, réglages, et `clean` pour les portefeuilles de `market`).
"""

from __future__ import annotations

import re
from typing import Any

from hub.core.connectors import Connector
from hub.core.errors import Problem

ENABLE_BANKING = ("aspsp_name", "aspsp_country", "psu_type", "consent_days", "max_syncs_per_day")
MAX_WALLETS = 50
WALLET_ASSETS = ("BTC", "ETH", "SOL", "ATOM")
WALLET_NETWORKS = ("ethereum", "arbitrum", "base", "bsc", "polygon")  # d'un portefeuille ETH
WALLET_ACCOUNT = re.compile(r"^crypto:[a-z0-9][a-z0-9-]{0,40}$")

# pays → modules de la finance qu'il ouvre (le pilier 3a en Suisse)
COUNTRY_MODULES: dict[str, frozenset[str]] = {"CH": frozenset({"pillar3a"})}


def clean_wallets(value: Any) -> list[dict[str, Any]]:
    """Portefeuilles suivis par le connecteur `market` : des adresses publiques ou la clé
    publique étendue d'un compte BTC, jamais une clé privée. Le collecteur revérifie tout."""
    if not isinstance(value, list) or len(value) > MAX_WALLETS:
        raise Problem("validation.params", f"portefeuilles : une liste, {MAX_WALLETS} au plus")
    out = []
    for w in value:
        if not isinstance(w, dict):
            raise Problem("validation.params", "portefeuille : un objet")
        account = str(w.get("account") or "")
        asset = str(w.get("asset") or "").upper()
        addresses = w.get("addresses") or []
        xpubs = w.get("xpubs") or ([w["xpub"]] if w.get("xpub") else [])
        if not WALLET_ACCOUNT.match(account):
            raise Problem("validation.params", "portefeuille : compte crypto:<nom>")
        if asset not in WALLET_ASSETS:
            raise Problem("validation.params", "portefeuille : BTC, ETH, SOL ou ATOM")
        if not isinstance(addresses, list) or not all(isinstance(a, str) for a in addresses):
            raise Problem("validation.params", "portefeuille : adresses en liste de textes")
        if not isinstance(xpubs, list) or not all(isinstance(x, str) for x in xpubs):
            raise Problem("validation.params", "portefeuille : clé publique en texte")
        if not (addresses or xpubs) or (xpubs and asset != "BTC"):
            raise Problem("validation.params", "portefeuille : adresses, ou xpub pour BTC")
        if any(x[1:4] == "prv" for x in xpubs):
            raise Problem("validation.params", "portefeuille : clé privée refusée")
        chains = w.get("networks") or []
        if not isinstance(chains, list) or not all(c in WALLET_NETWORKS for c in chains):
            raise Problem(
                "validation.params", f"portefeuille : réseaux parmi {', '.join(WALLET_NETWORKS)}"
            )
        if chains and asset != "ETH":
            raise Problem("validation.params", "portefeuille : réseaux pour ETH seulement")
        out.append({**w, "account": account, "asset": asset})
    return out


def clean_market(value: dict[str, Any]) -> dict[str, Any]:
    if "wallets" in value:
        return {**value, "wallets": clean_wallets(value["wallets"])}
    return value


CATALOG: tuple[Connector, ...] = (
    Connector(
        "bcf",
        "BCF",
        "browser",
        "CH",
        ("cash",),
        ("contract", "password"),
        "30 7 * * 1-5",  # jours ouvrés 07:30 (une seule validation du push)
        ("camt053",),
    ),
    Connector(
        "viac",
        "VIAC",
        "browser",
        "CH",
        ("pension",),
        ("email", "password"),
        "0 9 * * 0",  # dimanche 09:00
        ("viac_notice", "viac_report"),
    ),
    Connector(
        "enable_banking",
        "Banque européenne (Enable Banking)",
        "open_banking",
        None,
        ("cash",),
        ("application_id", "private_key"),
        "15 7,13,19 * * *",  # trois synchros, la quatrième reste pour la main (Revolut)
        ("revolut_eb",),
        ENABLE_BANKING,
        ("aspsp_name", "aspsp_country"),  # la banque, telle qu'Enable Banking la nomme
    ),
    Connector(
        "ibkr",
        "IBKR",
        "api",
        None,
        ("securities",),
        ("flex_token", "query_id"),
        "45 6 * * 2-6",  # relevé Flex de la veille, du mardi au samedi
        ("ibkr_flex",),
    ),
    Connector(
        "market",
        "Cours et cryptos",
        "public",
        None,
        ("crypto",),
        (),  # portefeuilles publics et clé CoinGecko facultatifs
        "15 6-22/4 * * *",  # cours et portefeuilles toutes les 4 h, de 06:15 à 22:15
        ("market",),
        ("currencies", "crypto", "quotes", "wallets"),
        single=True,  # tous les portefeuilles crypto dans la même connexion
        clean=clean_market,
    ),
    Connector(
        "binance",
        "Binance",
        "api",
        None,
        ("crypto",),
        ("api_key", "api_secret"),
        "20 6-22/4 * * *",  # soldes et opérations des plateformes, après les cours
        ("market",),
    ),
    Connector(
        "kucoin",
        "KuCoin",
        "api",
        None,
        ("crypto",),
        ("api_key", "api_secret", "passphrase"),
        "22 6-22/4 * * *",
        ("market",),
    ),
    Connector(
        "coinbase",
        "Coinbase",
        "api",
        None,
        ("crypto",),
        ("key_name", "private_key"),
        "24 6-22/4 * * *",
        ("market",),
    ),
)
NAMES: tuple[str, ...] = tuple(c.name for c in CATALOG)
