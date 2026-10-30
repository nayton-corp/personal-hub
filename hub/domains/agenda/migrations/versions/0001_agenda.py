"""agenda.db : le journal commun du contrat de domaine, et les envois au pont Rappels/Calendrier.

Les rappels et les événements vivent dans Rappels et Calendrier (macOS) : la base n'en garde
aucune copie. `sent` note chaque envoi au pont, avant puis après l'appel : une proposition
validée deux fois n'ajoute pas deux rappels, et la réconciliation sait ce qui est parti.

Revision ID: 0001_agenda
Revises:
Create Date: 2026-10-30
"""

from alembic import op

from hub.core import integrity

revision = "0001_agenda"
down_revision = None
branch_labels = None
depends_on = None

SENT = """
CREATE TABLE sent (                              -- un envoi au pont, par clé d'idempotence
  key          TEXT PRIMARY KEY,                 -- <proposition>:<révision>
  proposal_id  TEXT NOT NULL,
  kind         TEXT NOT NULL,
  params_json  TEXT NOT NULL,
  status       TEXT NOT NULL CHECK (status IN ('sending', 'ok', 'failed')),
  result_json  TEXT NOT NULL DEFAULT '{}',       -- l'identifiant rendu par le pont, jamais le texte
  sent_at      TEXT NOT NULL
)
"""


def upgrade() -> None:
    for statement in [*integrity.schema(), SENT, "CREATE INDEX sent_proposal ON sent(proposal_id)"]:
        op.execute(statement)


def downgrade() -> None:
    raise NotImplementedError("pas de retour arrière : restaurer la sauvegarde")
