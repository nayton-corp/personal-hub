"""Ce que tous les collecteurs partagent : résultats, échecs typés, réglages, mémoire locale.

Depuis G4, un service collecteur (`collector-api` ou `collector-browser`) exécute les connexions
que le hub lui donne : leurs réglages s'ajoutent à ceux de l'infrastructure (`[collectors]`),
leurs secrets arrivent chiffrés et ne sont déchiffrés qu'au moment du run."""

from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from hub.core import connectors, secrets
from hub.core.settings import Settings

Outcome = Literal[
    "ok",
    "nothing_new",
    "auth_pending_timeout",
    "site_unavailable",
    "selector_missing",
    "invalid_file",
    "auth_error",
    "unknown",
]
Kind = Literal["run", "check"]
NAMES = connectors.NAMES  # connecteurs que ce code sait exécuter
RUNNERS = connectors.RUNNERS


class Failure(Exception):
    """Un run qui s'arrête : le type d'échec de la section 8 et l'étape (jamais de contenu)."""

    def __init__(self, outcome: Outcome, detail: str) -> None:
        super().__init__(f"{outcome}: {detail}")
        self.outcome = outcome
        self.detail = detail


@dataclass
class Result:
    outcome: Outcome
    files: int = 0
    detail: str | None = None


class RevolutConfig(BaseModel):
    """Connecteur Enable Banking ; une connexion choisit sa banque (`aspsp_name`, `aspsp_country`)
    dans ses réglages. Le nom de la section vient du premier usage, Revolut."""

    aspsp_name: str = "Revolut"
    aspsp_country: str = "LT"  # clients suisses : Revolut Bank UAB (Lituanie), à confirmer
    psu_type: Literal["personal", "business"] = "personal"
    consent_days: int = Field(default=180, ge=1, le=730)
    max_syncs_per_day: int = Field(default=4, ge=1, le=4)  # limite Revolut sans l'utilisateur
    overlap_days: int = Field(default=10, ge=1, le=60)
    warn_days: int = Field(default=14, ge=1)  # alerte avant la fin du consentement
    api_url: str = "https://api.enablebanking.com"


class EvmNetwork(BaseModel):
    """Un réseau compatible Ethereum (couche 2, Polygon) : nœud public, et son historique par
    l'API Etherscan V2 (`chain_id`), qui demande une clé gratuite (`etherscan_key`)."""

    rpc_url: str
    chain_id: int
    native: str = "ETH"  # crypto qui paie le gaz
    tokens: dict[str, str] = {}  # contrat → symbole (le WETH compte comme ETH)


class MarketConfig(BaseModel):
    """Cours du marché (lot 6) : sources publiques, sans compte."""

    fx_url: str = "https://api.frankfurter.dev/v1"
    currencies: list[str] = ["EUR", "USD", "GBP"]
    coingecko_url: str = "https://api.coingecko.com/api/v3"
    crypto: dict[str, str] = {  # symbole → id CoinGecko
        "BTC": "bitcoin",
        "ETH": "ethereum",
        "SOL": "solana",
        "USDC": "usd-coin",
        "USDT": "tether",
        "POL": "polygon-ecosystem-token",
    }
    yahoo_url: str = "https://query1.finance.yahoo.com/v8/finance/chart"
    quotes: dict[str, str] = {}  # ISIN ou symbole → symbole Yahoo (par ex. « VWRL.SW »)
    # portefeuilles réglés dans l'app (G5) ; ceux des secrets d'avant G5 s'y ajoutent
    wallets: list[dict[str, Any]] = []
    mempool_url: str = "https://mempool.space/api"
    binance_url: str = "https://api.binance.com"  # clôtures publiques, pour l'historique
    mempool_pause_seconds: int = Field(default=1, ge=0, le=10)  # entre deux adresses BTC
    eth_rpc_url: str = "https://ethereum-rpc.publicnode.com"
    # historique Ethereum : un nœud public ne liste pas les transactions d'une adresse ; l'API
    # de Routescan (compatible Etherscan, sans clé) le fait. Blockscout sans clé coupe après
    # dix appels et protège ses couches 2 derrière Cloudflare.
    eth_history_url: str = "https://api.routescan.io/v2/network/mainnet/evm/1/etherscan/api"
    # historique des autres réseaux : Etherscan V2, une clé pour tous (`etherscan_key`)
    etherscan_url: str = "https://api.etherscan.io/v2/api"
    chain_pause_seconds: int = Field(default=1, ge=0, le=10)  # entre deux pages d'historique
    coingecko_pause_seconds: int = Field(default=3, ge=0, le=30)  # entre deux cours, sans clé
    solana_rpc_url: str = "https://api.mainnet-beta.solana.com"
    # jetons lus en plus de la crypto native ; les autres (souvent du spam) sont ignorés
    erc20_tokens: dict[str, str] = {  # symbole → contrat Ethereum
        "USDC": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
        "USDT": "0xdAC17F958D2ee523a2206206994597C13D831ec7",
    }
    # réseaux lus en plus d'Ethereum, pour un portefeuille qui les nomme (`networks`)
    evm_networks: dict[str, EvmNetwork] = {
        "arbitrum": EvmNetwork(
            rpc_url="https://arbitrum-one-rpc.publicnode.com",
            chain_id=42161,
            tokens={
                "0xaf88d065e77c8cC2239327C5EDb3A432268e5831": "USDC",
                "0xFd086bC7CD5C481DCC9C85ebE478A1C0b69FCbb9": "USDT",
                "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1": "ETH",
            },
        ),
        "base": EvmNetwork(
            rpc_url="https://base-rpc.publicnode.com",
            chain_id=8453,
            tokens={
                "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913": "USDC",
                "0x4200000000000000000000000000000000000006": "ETH",
            },
        ),
        "polygon": EvmNetwork(
            rpc_url="https://polygon-bor-rpc.publicnode.com",
            chain_id=137,
            native="POL",
            tokens={
                "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359": "USDC",
                "0xc2132D05D31c914a87C6611C10748AEb04B58e8F": "USDT",
                "0x7ceB23fD6bC0adD59E62ac25578270cFf1b9f619": "ETH",
            },
        ),
    }
    # jetons de staking (Ethereum) : contrat → crypto mise en jeu, comptée à sa quantité
    # sous-jacente (`balanceOfUnderlying`, sinon une part pour une unité)
    staking_tokens: dict[str, str] = {
        "0x30a4aa1d14D44f0f5BFe887447AB6FAcc94A549F": "ETH",  # Kiln Native20 (cbwsETH)
    }
    spl_tokens: dict[str, str] = {  # mint Solana → symbole
        "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": "USDC",
        "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB": "USDT",
    }
    gap_limit: int = Field(
        default=20, ge=1, le=100
    )  # adresses vides de suite avant d'arrêter (xpub)
    backfill_days: int = Field(default=365, ge=1, le=365)


class ExchangesConfig(BaseModel):
    """Plateformes crypto (Binance, KuCoin, Coinbase) : API officielles, clés en lecture seule."""

    binance_url: str = "https://api.binance.com"
    kucoin_url: str = "https://api.kucoin.com"
    coinbase_url: str = "https://api.coinbase.com"
    aliases: dict[str, str] = {"ETH2": "ETH"}  # symbole de la plateforme → symbole suivi
    # historique Binance : premier jour cherché (le secret `since` le remplace) et pauses
    # entre deux appels (l'historique des retraits est limité à dix appels par minute)
    binance_since: str = "2017-07-01"
    history_pause_ms: int = Field(default=250, ge=0, le=10_000)
    withdraw_pause_ms: int = Field(default=6_000, ge=0, le=60_000)


class CollectorConfig(BaseModel):
    """Section `[collectors]` des réglages (sans secret)."""

    api_url: str = "http://api:8710"
    home: Path = Path("/var/lib/hub-collector")
    headless: bool = True
    bcf_overlap_days: int = Field(default=10, ge=1, le=90)
    viac_overlap_days: int = Field(default=14, ge=0, le=90)
    viac_report_every_days: int = Field(default=6, ge=1)
    diag_keep_days: int = Field(default=7, ge=1)
    check_poll_seconds: int = Field(default=60, ge=10)
    urls: dict[str, str] = {}  # « bcf.url » : remplace une adresse de `[site]` (faux site)
    revolut: RevolutConfig = RevolutConfig()
    market: MarketConfig = MarketConfig()
    exchanges: ExchangesConfig = ExchangesConfig()

    @property
    def profiles(self) -> Path:
        return self.home / "profiles"

    @property
    def diag(self) -> Path:
        return self.home / "diag"

    @property
    def state_dir(self) -> Path:
        return self.home / "state"


# section de `[collectors]` que les réglages d'une connexion complètent, par connecteur
SECTIONS = {"enable_banking": "revolut", "market": "market"}


def config(settings: Settings) -> CollectorConfig:
    raw = dict(settings.domain("collectors"))
    raw.pop("schedules", None)  # avant G4 : les horaires vivent désormais dans les connexions
    return CollectorConfig.model_validate(raw)


def for_connection(cfg: CollectorConfig, connector: str, values: dict[str, Any]) -> CollectorConfig:
    """Les réglages d'une connexion par-dessus ceux du service ; un réglage invalide échoue."""
    section = SECTIONS.get(connector)
    if section is None or not values:
        return cfg
    current = getattr(cfg, section)
    merged = type(current).model_validate({**current.model_dump(), **values})
    return cfg.model_copy(update={section: merged})


def service_token(settings: Settings, runner: str) -> str | None:
    """Jeton du service (`core:collector`), section `collector-<service>` de son fichier de
    secrets ; les secrets des connexions, eux, viennent du hub."""
    section = secrets.section(
        settings.secrets.file, settings.secrets.age_key_file, f"collector-{runner}"
    )
    token = section.get("token")
    return token if isinstance(token, str) and token else None


def open_secrets(settings: Settings, blob: str | None) -> dict[str, Any]:
    """Secrets d'une connexion (fichier age en base64) → dictionnaire, au moment du run."""
    if not blob:
        return {}
    plain = secrets.decrypt_with(settings.secrets.age_key_file, base64.b64decode(blob))
    data = json.loads(plain)
    if not isinstance(data, dict):
        raise secrets.SecretsError("secrets de connexion invalides")
    return data


class Memory:
    """Mémoire d'un collecteur (empreintes déjà vues, dates, session) : un fichier JSON dans son
    volume, réécrit de façon atomique. Jamais de contenu bancaire."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.data: dict[str, Any] = json.loads(path.read_text()) if path.exists() else {}

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def put(self, key: str, value: Any) -> None:
        self.data[key] = value

    def seen(self) -> set[str]:
        return set(self.data.get("seen", []))

    def remember(self, digest: str) -> None:
        seen = list(self.data.get("seen", []))
        if digest not in seen:
            seen.append(digest)
        self.data["seen"] = seen[-5000:]

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=1, sort_keys=True))
        os.chmod(tmp, 0o600)
        tmp.replace(self.path)
