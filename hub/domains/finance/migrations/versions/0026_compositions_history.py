"""finance.db : les compositions de fonds sont versionnées (audit m16). `compositions` garde
chaque composition publiée avec sa date : la clé primaire comprend `on_date`, un import n'efface
plus la composition d'avant ; une répartition à une date lit la dernière composition connue à
cette date. La table est rebâtie ligne pour ligne (SQLite ne sait pas changer une clé primaire
autrement) ; ce n'est pas un registre.

Revision ID: 0026_compositions_history
Revises: 0025_debt_day_count
Create Date: 2026-11-04
"""

from __future__ import annotations

from alembic import op

revision = "0026_compositions_history"
down_revision = "0025_debt_day_count"
branch_labels = None
depends_on = None

STATEMENTS = [
    # ledger-migration: reviewed — compositions n'est pas un registre : recopiée ligne pour ligne
    """
    CREATE TABLE compositions_v2 (                   -- transparence d'un fonds, par dimension
      isin      TEXT NOT NULL,
      dimension TEXT NOT NULL CHECK (dimension IN ('region','sector','currency','holding')),
      bucket    TEXT NOT NULL,                       -- 'Amérique du Nord', 'Technologie', 'USD'
      weight    TEXT NOT NULL,                       -- Decimal entre 0 et 1, en texte
      on_date   TEXT NOT NULL,                       -- date de la composition publiée
      import_id TEXT REFERENCES imports(id),
      PRIMARY KEY (isin, dimension, on_date, bucket)
    )
    """,
    "INSERT INTO compositions_v2 (isin, dimension, bucket, weight, on_date, import_id) "
    "SELECT isin, dimension, bucket, weight, on_date, import_id FROM compositions "
    "ORDER BY isin, dimension, bucket",
    "DROP TABLE compositions",
    "ALTER TABLE compositions_v2 RENAME TO compositions",
]


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    raise NotImplementedError("pas de retour arrière : restaurer la sauvegarde")
