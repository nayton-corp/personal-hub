"""finance.db : objectif des comptes et valeur par compte dans les instantanés.

`accounts.goal` classe un compte par usage (courant, réserve, projets, long terme, retraite) ;
NULL laisse l'app le déduire du type de compte. `snapshots.by_account_json` garde la valeur de
chaque compte à chaque date, pour que la courbe suive les filtres de l'app. Les instantanés
sont dérivés : l'état est effacé pour qu'ils soient recalculés au prochain accès.

Revision ID: 0012_account_goal
Revises: 0011_crypto_journal
Create Date: 2026-10-28
"""

from alembic import op

revision = "0012_account_goal"
down_revision = "0011_crypto_journal"
branch_labels = None
depends_on = None

STATEMENTS = [
    "ALTER TABLE accounts ADD COLUMN goal TEXT CHECK (goal IN "
    "('current','safety','projects','long_term','retirement'))",
    "ALTER TABLE snapshots ADD COLUMN by_account_json TEXT NOT NULL DEFAULT '{}'",
    "DELETE FROM snapshot_state",
]


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    raise NotImplementedError("pas de retour arrière : restaurer la sauvegarde")
