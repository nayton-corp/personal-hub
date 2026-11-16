"""finance.db : d'où vient le TER d'un fonds, en ajout seul.

Le TER publié d'un fonds est désormais relevé par le collecteur « market » (liste de fonds d'une
plateforme, fiche du fonds) et déposé comme un fichier : la ligne porte `source = 'issuer'`, le
site lu (`origin`, par ex. « viac.ch ») et l'import qui l'a apportée (`import_id`). Une saisie à
la main (`source = 'user'`) n'a ni l'un ni l'autre, et l'emporte toujours sur un TER relevé.

Revision ID: 0031_fund_fee_origin
Revises: 0030_strategy_origin
Create Date: 2026-11-16
"""

from __future__ import annotations

from alembic import op

revision = "0031_fund_fee_origin"
down_revision = "0030_strategy_origin"
branch_labels = None
depends_on = None

STATEMENTS = [
    "ALTER TABLE fund_fees ADD COLUMN origin TEXT",
    "ALTER TABLE fund_fees ADD COLUMN import_id TEXT",
]


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    raise NotImplementedError("pas de retour arrière : restaurer la sauvegarde")
