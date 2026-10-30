"""documents.db : fiches d'objets, documents et marques « foyer », en ajout seul et chaînés ;
les passages indexés, eux, se recalculent depuis l'archive.

Une fiche change par une nouvelle version (la dernière fait foi) ; un document ne change jamais,
sa marque « foyer » (lisible par l'assistant pour tout le foyer) s'ajoute à côté.

Revision ID: 0001_documents
Revises:
Create Date: 2026-10-30
"""

from alembic import op

from hub.core import integrity

revision = "0001_documents"
down_revision = None
branch_labels = None
depends_on = None

SCHEMA = [
    """
    CREATE TABLE cards (                         -- une version de fiche d'objet
      seq          INTEGER PRIMARY KEY,
      card_id      TEXT NOT NULL,
      fields_json  TEXT NOT NULL,
      at           TEXT NOT NULL,
      hash_v       INTEGER NOT NULL
    )
    """,
    "CREATE INDEX cards_id ON cards(card_id, seq)",
    """
    CREATE TABLE documents (                     -- un document archivé, jamais modifié
      seq        INTEGER PRIMARY KEY,
      id         TEXT NOT NULL UNIQUE,
      title      TEXT NOT NULL,
      file_name  TEXT NOT NULL,
      sha256     TEXT NOT NULL,
      mime       TEXT NOT NULL,
      card_id    TEXT,                           -- l'objet qu'il documente, ou aucun
      at         TEXT NOT NULL,
      hash_v     INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE marks (                         -- la marque « foyer » d'un document
      seq          INTEGER PRIMARY KEY,
      document_id  TEXT NOT NULL,
      household    INTEGER NOT NULL CHECK (household IN (0, 1)),
      at           TEXT NOT NULL,
      hash_v       INTEGER NOT NULL
    )
    """,
    "CREATE INDEX marks_document ON marks(document_id, seq)",
    """
    CREATE TABLE passages (                      -- l'index local, recalculable
      seq          INTEGER PRIMARY KEY,
      document_id  TEXT NOT NULL,
      page         INTEGER,
      text         TEXT NOT NULL
    )
    """,
    "CREATE INDEX passages_document ON passages(document_id)",
    """
    CREATE VIRTUAL TABLE passages_fts USING fts5(
      text, content = 'passages', content_rowid = 'seq', tokenize = 'trigram'
    )
    """,
    """
    CREATE TRIGGER passages_fts_insert AFTER INSERT ON passages BEGIN
      INSERT INTO passages_fts(rowid, text) VALUES (new.seq, new.text);
    END
    """,
    """
    CREATE TRIGGER passages_fts_delete AFTER DELETE ON passages BEGIN
      INSERT INTO passages_fts(passages_fts, rowid, text) VALUES ('delete', old.seq, old.text);
    END
    """,
]


def upgrade() -> None:
    for statement in [
        *integrity.schema(),
        *SCHEMA,
        *integrity.append_only("cards"),
        *integrity.append_only("documents"),
        *integrity.append_only("marks"),
    ]:
        op.execute(statement)


def downgrade() -> None:
    raise NotImplementedError("pas de retour arrière : restaurer la sauvegarde")
