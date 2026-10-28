"""Catalogue des connecteurs (chantier « hub générique », G3).

Chaque source de données que le hub sait collecter est déclarée ici, une fois : son nom, sa
méthode, son pays, les types de comptes qu'elle alimente, les champs de secrets qu'elle attend,
les réglages qu'elle accepte et son horaire par défaut. Une *connexion* (G4, `connections` dans
`core.db`) est l'usage d'un connecteur par l'instance : un identifiant (« revolut »), ses
secrets chiffrés, son horaire et ses réglages. Un même connecteur peut servir plusieurs
connexions, par exemple Enable Banking pour deux banques.

Méthodes, par ordre de préférence : `open_banking` (Enable Banking, banques de l'UE), `api`
(API officielle du fournisseur, clé en lecture seule), `public` (données publiques, sans
compte), `browser` (robot qui télécharge l'export officiel, seulement sans autre accès).
Le dépôt manuel d'un fichier (camt.053, CSV, PDF) reste toujours possible, sans connecteur.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

Method = Literal["open_banking", "api", "public", "browser"]
METHODS: tuple[Method, ...] = ("open_banking", "api", "public", "browser")
Runner = Literal["api", "browser"]
RUNNERS: tuple[Runner, ...] = ("api", "browser")
ENABLE_BANKING = ("aspsp_name", "aspsp_country", "psu_type", "consent_days", "max_syncs_per_day")


@dataclass(frozen=True)
class Connector:
    name: str
    label: str
    method: Method
    country: str | None  # ISO 3166-1, ou None pour un service international
    accounts: tuple[str, ...]  # types de comptes alimentés (cash, pension, securities, crypto)
    secrets: tuple[str, ...]  # champs obligatoires de la section `collector-<nom>`
    schedule: str  # horaire par défaut, fuseau de l'instance
    formats: tuple[str, ...]  # sources d'import des fichiers qu'il dépose (`imports.source`)
    settings: tuple[str, ...] = ()  # réglages sans secret qu'une connexion peut donner
    required: tuple[str, ...] = ()  # réglages qu'une nouvelle connexion doit donner

    @property
    def runner(self) -> Runner:
        """Service collecteur qui l'exécute : les robots ont Chromium, les autres non."""
        return "browser" if self.method == "browser" else "api"

    def public(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "method": self.method,
            "country": self.country,
            "accounts": list(self.accounts),
            "secrets": list(self.secrets),
            "schedule": self.schedule,
            "formats": list(self.formats),
            "settings": list(self.settings),
            "required_settings": list(self.required),
            "runner": self.runner,
        }


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
        "15 6 * * *",  # cours de la veille, tous les jours
        ("market",),
        ("currencies", "crypto", "quotes"),
    ),
    Connector(
        "binance",
        "Binance",
        "api",
        None,
        ("crypto",),
        ("api_key", "api_secret"),
        "20 6 * * *",  # soldes des plateformes, après les cours
        ("market",),
    ),
    Connector(
        "kucoin",
        "KuCoin",
        "api",
        None,
        ("crypto",),
        ("api_key", "api_secret", "passphrase"),
        "22 6 * * *",
        ("market",),
    ),
    Connector(
        "coinbase",
        "Coinbase",
        "api",
        None,
        ("crypto",),
        ("key_name", "private_key"),
        "24 6 * * *",
        ("market",),
    ),
)
NAMES: tuple[str, ...] = tuple(c.name for c in CATALOG)
_BY_NAME = {c.name: c for c in CATALOG}


def get(name: str) -> Connector | None:
    return _BY_NAME.get(name)
