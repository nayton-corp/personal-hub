"""finance.db : suivi de performance des cryptos.

Les paiements de la catégorie « Crypto » (virements vers SwissBorg, Binance, Coinbase…) achètent
des cryptos tenues hors registre : comme « Achats et ventes de titres », ils ne sortent plus du
patrimoine (calcul dans `valuation`, sans changement de schéma). Cette révision ajoutait les
règles de départ de la catégorie (KuCoin et d'autres plateformes courantes) aux bases qui avaient
les règles « seed- » ; depuis le chantier « hub générique » (G2), elles sont dans les packs et
une base neuve n'a plus rien à recevoir ici.

Revision ID: 0008_crypto_cost
Revises: 0007_alerts
Create Date: 2026-10-28
"""

revision = "0008_crypto_cost"
down_revision = "0007_alerts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Rien pour une base créée après G2 ; une base plus ancienne l'a déjà appliquée."""


def downgrade() -> None:
    raise NotImplementedError("pas de retour arrière : restaurer la sauvegarde")
