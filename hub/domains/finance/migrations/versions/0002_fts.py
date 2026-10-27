"""finance.db : recherche plein texte trigram sur `search_text` (spécification, section 7).

Revision ID: 0002_fts
Revises: 0001_ledger
Create Date: 2026-10-27
"""

from alembic import op

revision = "0002_fts"
down_revision = "0001_ledger"
branch_labels = None
depends_on = None

STATEMENTS = [
    """
    CREATE VIRTUAL TABLE entries_fts USING fts5(
      search_text, content = 'entries', content_rowid = 'seq', tokenize = 'trigram'
    )
    """,
    # une écriture n'est jamais modifiée ni supprimée : l'insertion suffit
    """
    CREATE TRIGGER entries_fts_insert AFTER INSERT ON entries BEGIN
      INSERT INTO entries_fts(rowid, search_text) VALUES (new.seq, new.search_text);
    END
    """,
    """
    CREATE VIRTUAL TABLE notes_fts USING fts5(
      search_text, content = 'notes', content_rowid = 'seq', tokenize = 'trigram'
    )
    """,
    """
    CREATE TRIGGER notes_fts_insert AFTER INSERT ON notes BEGIN
      INSERT INTO notes_fts(rowid, search_text) VALUES (new.seq, new.search_text);
    END
    """,
]


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    raise NotImplementedError("pas de retour arrière : restaurer la sauvegarde")
