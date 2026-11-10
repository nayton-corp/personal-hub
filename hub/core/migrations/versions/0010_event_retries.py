"""core.db : file de renvoi des événements des domaines (audit du 10/11, N1 et N3). Une
notification que ntfy n'a pas prise, ou un événement dont le traitement lève une erreur, y attend
le passage suivant au lieu d'être perdu (le curseur avançait quand même) ou de bloquer la file de
son domaine. Après quelques essais, la ligne est mise de côté (`set_aside`) et reste lisible.

# ledger-migration: reviewed

Revision ID: 0010_event_retries
Revises: 0009_passkey_revoked
Create Date: 2026-11-10
"""

from alembic import op

revision = "0010_event_retries"
down_revision = "0009_passkey_revoked"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE event_retries (
          domain     TEXT NOT NULL,
          seq        INTEGER NOT NULL,
          type       TEXT NOT NULL,
          payload    TEXT NOT NULL,              -- JSON de l'événement, tel que le domaine l'a écrit
          status     TEXT NOT NULL CHECK (status IN ('waiting','set_aside')),
          attempts   INTEGER NOT NULL,
          last_error TEXT,                       -- le type de l'erreur, jamais son texte
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          PRIMARY KEY (domain, seq)
        )
        """
    )


def downgrade() -> None:
    raise NotImplementedError("pas de retour arrière : restaurer la sauvegarde")
