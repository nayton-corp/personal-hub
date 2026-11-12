"""finance.db : stratégies (vendre par paliers, achat régulier, acheter une grosse baisse).

Une stratégie est une décision écrite une fois : sur quoi (`scope` : un instrument, ou un
groupe `crypto:alt`, `crypto:all`), un genre et ses réglages (`params_json` : des seuils, des
montants, des dates, rien d'autre : le même calcul sert chaque nuit et pour un rejeu sur le
passé). Le hub ne passe jamais d'ordre : il ouvre une étape quand la condition est remplie
(`strategy_steps`, une ligne par étape atteinte, une seule fois par clé), prévient, puis constate
l'opération au journal ou prend la réponse de la personne.

Revision ID: 0027_strategies
Revises: 0026_compositions_history
Create Date: 2026-11-12
"""

from __future__ import annotations

from alembic import op

revision = "0027_strategies"
down_revision = "0026_compositions_history"
branch_labels = None
depends_on = None

STATEMENTS = [
    """
    CREATE TABLE strategies (
      id          TEXT PRIMARY KEY,                  -- ULID
      kind        TEXT NOT NULL CHECK (kind IN ('ladder','recurring','dip')),
      scope       TEXT NOT NULL,                     -- 'CRYPTO:BTC', un ISIN, 'crypto:alt', 'crypto:all'
      name        TEXT NOT NULL,                     -- 'Altcoins'
      params_json TEXT NOT NULL,                     -- réglages du genre (seuils, montants, dates)
      note        TEXT,                              -- « ensuite » : ce que la personne fera après
      status      TEXT NOT NULL CHECK (status IN ('active','paused','ended')),
      created_on  TEXT NOT NULL,                     -- jour civil : rien n'est dû avant
      created_at  TEXT NOT NULL,
      updated_at  TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE strategy_steps (                    -- une étape atteinte
      id           TEXT PRIMARY KEY,                 -- ULID, opaque (lien d'une notification)
      strategy_id  TEXT NOT NULL REFERENCES strategies(id),
      step_key     TEXT NOT NULL,                    -- 't100' (palier), '2026-11' (mois), 'p2026-10-02'
      state        TEXT NOT NULL CHECK (state IN ('open','later','done','skipped')),
      opened_on    TEXT NOT NULL,
      planned_minor INTEGER,                         -- ce qui était prévu, centimes de la devise de base
      done_minor   INTEGER NOT NULL DEFAULT 0,       -- ce que le journal montre depuis
      detail_json  TEXT NOT NULL DEFAULT '{}',       -- le niveau le jour de l'alerte
      closed_on    TEXT,
      closed_by    TEXT CHECK (closed_by IN ('journal','user','expired')),
      proposal_id  TEXT,
      created_at   TEXT NOT NULL,
      updated_at   TEXT NOT NULL,
      UNIQUE (strategy_id, step_key)
    )
    """,
]


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    raise NotImplementedError("pas de retour arrière : restaurer la sauvegarde")
