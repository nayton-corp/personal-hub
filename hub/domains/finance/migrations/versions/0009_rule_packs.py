"""finance.db : packs de règles installés (chantier « hub générique », G2).

Les règles de départ ne viennent plus des migrations mais de packs YAML versionnés
(`hub/domains/finance/packs/`). Cette table retient la version installée de chacun. Une base
existante garde ses règles de départ (« seed- ») et n'a aucun pack installé.

Revision ID: 0009_rule_packs
Revises: 0008_crypto_cost
Create Date: 2026-10-28
"""

from alembic import op

revision = "0009_rule_packs"
down_revision = "0008_crypto_cost"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE rule_packs (                    -- packs de règles installés
          name         TEXT PRIMARY KEY,
          version      INTEGER NOT NULL CHECK (version >= 1),
          installed_at TEXT NOT NULL
        )
        """
    )


def downgrade() -> None:
    raise NotImplementedError("pas de retour arrière : restaurer la sauvegarde")
