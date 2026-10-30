"""Manifeste de la finance (chantier S2) : ce qu'elle apporte à l'app, à la boîte d'entrée et à
l'assistant. Les modules nommés sont des fichiers de son dossier `web/`."""

from __future__ import annotations

from pathlib import Path

from hub.core.manifest import AppModule, HomeCard, Importer, Manifest, SettingsSection, Tab
from hub.domains.finance.sources.app.connectors import NAMES
from hub.domains.finance.sources.app.importer import INBOX_SUFFIXES

DESCRIPTION = (
    "Finances personnelles : comptes, dépenses par catégorie, budget, patrimoine, "
    "abonnements ; propositions de catégorie, de règle, de budget et de note."
)

# tables en ajout seul : un trigger refuse UPDATE et DELETE (migrations 0001 et 0005)
PROTECTED = frozenset(
    {
        "applied_proposals",
        "budgets",
        "categorization_lines",
        "categorizations",
        "checkpoints",
        "entries",
        "events",
        "holdings",
        "journal",
        "notes",
        "prices",
        "taggings",
        "tags",
        "trades",
    }
)

ASSISTANT = (
    "Montants en texte décimal avec leur devise, jamais arrondis ni convertis de tête. Avec la "
    "seule portée finance:aggregates, ne parler que de totaux (catégories, mois, comptes) : pas "
    "d'écriture isolée, pas de contrepartie. Rien ne s'écrit sans proposition : classer, créer "
    "une règle, fixer un budget ou noter passe par une carte que la personne valide dans l'app."
)

MANIFEST = Manifest(
    description=DESCRIPTION,
    app=AppModule(
        tabs=(
            Tab("patrimoine", "Patrimoine", "trend", "wealth.js", order=20),
            Tab("budget", "Budget", "wallet", "budget.js", order=30),
            Tab("journal", "Journal", "list", "journal.js", order=40),
        ),
        home_cards=(
            HomeCard("bilan", "Chiffres clés du mois", "/kpis"),
            HomeCard("alertes", "À traiter", "/alerts"),
            HomeCard("budget", "Budget du mois", "/budget"),
        ),
        settings=(
            SettingsSection("conn", "Connexions", "plug", "Données", "settings.js"),
            SettingsSection("accounts", "Comptes", "wallet", "Données", "settings.js"),
            SettingsSection("debts", "Dettes", "landmark", "Données", "settings.js"),
            SettingsSection("export", "Exporter", "download", "Données", "settings.js"),
            SettingsSection("budget", "Budget", "piggy", "Préférences", "settings.js"),
            SettingsSection("tax", "Impôts et 3a", "shield", "Préférences", "settings.js"),
        ),
        cards="proposals.js",
        home="home.js",
        module="finance.js",
        web=Path(__file__).parent / "web",
    ),
    importers=(
        Importer(
            "releves",
            "Relevés, rapports et avis (camt.053, VIAC, Revolut, IBKR, plateformes crypto)",
            INBOX_SUFFIXES,
        ),
    ),
    connectors=NAMES,
    protected_tables=PROTECTED,
    assistant=ASSISTANT,
)
