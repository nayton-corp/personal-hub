"""finance.db : biens hors comptes (logement, véhicule, objet de valeur, prêt accordé).

Un bien n'a ni relevé ni cours : sa valeur est saisie à une date (`good_value_records`, en ajout
seul ; la dernière valeur posée pour un même jour fait foi), puis suit, si la personne le veut,
une variation annuelle (`yearly_change` : -0.15 pour une voiture qui perd 15 % par an). Le
patrimoine l'ajoute (enveloppe « biens », clé `good:<id>`) ; il ne compte pas dans le rendement.

Revision ID: 0028_goods
Revises: 0027_strategies
Create Date: 2026-11-13
"""

from __future__ import annotations

from alembic import op

revision = "0028_goods"
down_revision = "0027_strategies"
branch_labels = None
depends_on = None

STATEMENTS = [
    """
    CREATE TABLE goods (
      id            TEXT PRIMARY KEY,                  -- ULID
      name          TEXT NOT NULL,                     -- 'Appartement', 'Voiture'
      kind          TEXT NOT NULL CHECK (kind IN ('home','vehicle','object','loan','other')),
      currency      TEXT NOT NULL REFERENCES currencies(code),
      yearly_change TEXT,                              -- décimal : '-0.15' ; NULL : valeur fixe
      closed_on     TEXT,                              -- vendu, donné, remboursé : vaut 0 dès ce jour
      created_at    TEXT NOT NULL,
      updated_at    TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE good_value_records (                  -- valeurs saisies, en ajout seul
      id           TEXT PRIMARY KEY,
      good_id      TEXT NOT NULL REFERENCES goods(id),
      on_date      TEXT NOT NULL,
      amount_minor INTEGER NOT NULL CHECK (amount_minor >= 0),
      proposal_id  TEXT,
      created_at   TEXT NOT NULL
    )
    """,
    "CREATE INDEX good_value_records_day ON good_value_records(good_id, on_date)",
]


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    raise NotImplementedError("pas de retour arrière : restaurer la sauvegarde")
