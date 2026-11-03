"""core.db : une passkey se retire (audit M16), en ajout seul : `revoked_at` la met de côté,
ses sessions sont fermées, la ligne reste (journal d'audit lisible). Le défi `confirm` (Face ID
d'une passkey en place avant d'en ajouter ou d'en retirer une) élargit le CHECK de
`webauthn_challenges` : la table est rebâtie à l'identique, ses lignes recopiées (des défis
éphémères, expirés en quelques minutes).

# ledger-migration: reviewed

Revision ID: 0009_passkey_revoked
Revises: 0008_core_ledger
Create Date: 2026-11-03
"""

from alembic import op

revision = "0009_passkey_revoked"
down_revision = "0008_core_ledger"
branch_labels = None
depends_on = None

CHALLENGES = """
CREATE TABLE webauthn_challenges_v2 (
  id           TEXT PRIMARY KEY,
  purpose      TEXT NOT NULL CHECK (purpose IN ('register','login','approve','confirm')),
  challenge    BLOB NOT NULL,
  bound_digest TEXT,
  expires_at   TEXT NOT NULL
)
"""


def upgrade() -> None:
    op.execute("ALTER TABLE passkeys ADD COLUMN revoked_at TEXT")
    op.execute(CHALLENGES)
    op.execute(
        "INSERT INTO webauthn_challenges_v2 (id, purpose, challenge, bound_digest, expires_at) "
        "SELECT id, purpose, challenge, bound_digest, expires_at FROM webauthn_challenges "
        "ORDER BY expires_at, id"
    )
    op.execute("DROP TABLE webauthn_challenges")
    op.execute("ALTER TABLE webauthn_challenges_v2 RENAME TO webauthn_challenges")


def downgrade() -> None:
    raise NotImplementedError("pas de retour arrière : restaurer la sauvegarde")
