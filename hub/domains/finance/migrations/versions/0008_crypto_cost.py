"""finance.db : suivi de performance des cryptos.

Les paiements de la catégorie « Crypto » (virements vers SwissBorg, Binance, Coinbase…) achètent
des cryptos tenues hors registre : comme « Achats et ventes de titres », ils ne sortent plus du
patrimoine (calcul dans `valuation`, sans changement de schéma). Cette révision ajoute seulement
les règles de départ de la catégorie qui manquent (KuCoin), sans recréer une règle supprimée
d'une autre catégorie.

Revision ID: 0008_crypto_cost
Revises: 0007_alerts
Create Date: 2026-10-28
"""

from alembic import op
from sqlalchemy import text

from hub.domains.finance import legacy

revision = "0008_crypto_cost"
down_revision = "0007_alerts"
branch_labels = None
depends_on = None

CREATED_AT = "2026-10-28T00:00:00.000Z"


def upgrade() -> None:
    conn = op.get_bind()
    if conn.execute(text("SELECT 1 FROM categories WHERE id = 'crypto'")).first() is None:
        return
    specs, _needed = legacy.convert(legacy.DEFAULT_RULES)
    for s in specs:
        if s.category_id != "crypto" or s.pattern != "kucoin":
            continue
        conn.execute(
            text(
                "INSERT OR IGNORE INTO rules (id, field, pattern, direction, category_id, "
                "priority, created_at) VALUES (:id, :f, :p, :d, :c, :prio, :at)"
            ),
            {
                "id": s.id("seed"),
                "f": s.field,
                "p": s.pattern,
                "d": s.direction,
                "c": s.category_id,
                "prio": s.priority,
                "at": CREATED_AT,
            },
        )
    conn.execute(text("UPDATE rules_meta SET version = version + 1"))


def downgrade() -> None:
    raise NotImplementedError("pas de retour arrière : restaurer la sauvegarde")
