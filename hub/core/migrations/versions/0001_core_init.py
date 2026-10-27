"""core.db : accès, propositions, trace (spécification, section 3, revue d'architecture incluse).

Revision ID: 0001_core_init
Revises:
Create Date: 2026-10-27
"""

from alembic import op

revision = "0001_core_init"
down_revision = None
branch_labels = None
depends_on = None

PROTECTED = ("audit", "links")

STATEMENTS = [
    """
    CREATE TABLE tokens (
      id           TEXT PRIMARY KEY,                 -- ULID, affiché dans l'app
      name         TEXT NOT NULL,                    -- 'brain-mac', 'collector-bcf'
      scopes       TEXT NOT NULL,                    -- portées qualifiées, séparées par des espaces
      secret_hash  TEXT NOT NULL UNIQUE,             -- sha256 du jeton, jamais stocké en clair
      created_at   TEXT NOT NULL,
      last_used_at TEXT,
      revoked_at   TEXT
    )
    """,
    """
    CREATE TABLE passkeys (
      credential_id TEXT PRIMARY KEY,                -- base64url
      public_key    BLOB NOT NULL,
      sign_count    INTEGER NOT NULL,
      device_name   TEXT,
      transports    TEXT,
      created_at    TEXT NOT NULL,
      last_used_at  TEXT
    )
    """,
    """
    CREATE TABLE sessions (                          -- cookie de session de l'app après passkey
      id            TEXT PRIMARY KEY,                -- sha256 du cookie, jamais le cookie lui-même
      credential_id TEXT NOT NULL REFERENCES passkeys(credential_id),
      created_at    TEXT NOT NULL,
      expires_at    TEXT NOT NULL,
      revoked_at    TEXT
    )
    """,
    """
    CREATE TABLE bootstrap_codes (                   -- code à usage unique pour inscrire une passkey
      id         TEXT PRIMARY KEY,
      code_hash  TEXT NOT NULL UNIQUE,
      created_at TEXT NOT NULL,
      expires_at TEXT NOT NULL,
      used_at    TEXT
    )
    """,
    """
    CREATE TABLE proposals (
      id             TEXT PRIMARY KEY,               -- ULID
      domain         TEXT NOT NULL,
      kind           TEXT NOT NULL,
      params_json    TEXT NOT NULL,
      params_hash    TEXT NOT NULL,                  -- sha256 des paramètres canoniques
      preview_json   TEXT NOT NULL,
      fingerprint    TEXT NOT NULL,                  -- empreinte de l'état lu (section 5)
      revision       INTEGER NOT NULL DEFAULT 1,     -- verrou optimiste
      status         TEXT NOT NULL CHECK (status IN ('pending','applying','applied','rejected',
                       'expired','superseded','obsolete','failed','unknown')),
      tier           TEXT NOT NULL DEFAULT 'human' CHECK (tier IN ('human','auto_digest','auto')),
      created_by     TEXT NOT NULL,                  -- URN d'acteur, sans clé étrangère
      reason         TEXT,
      bundle_id      TEXT,
      create_key     TEXT UNIQUE,                    -- en-tête Idempotency-Key de la création
      signature_json TEXT,                           -- assertion WebAuthn de la validation
      created_at     TEXT NOT NULL,
      expires_at     TEXT NOT NULL,
      claimed_at     TEXT,                           -- passage en applying (réconciliation)
      decided_at     TEXT,
      result_json    TEXT
    )
    """,
    "CREATE INDEX proposals_status ON proposals(status, created_at)",
    "CREATE INDEX proposals_bundle ON proposals(bundle_id) WHERE bundle_id IS NOT NULL",
    """
    CREATE UNIQUE INDEX proposals_one_pending ON proposals(domain, kind, params_hash)
    WHERE status = 'pending'
    """,
    """
    CREATE TABLE audit (                             -- jamais de contenu financier
      seq     INTEGER PRIMARY KEY,
      at      TEXT NOT NULL,
      actor   TEXT NOT NULL,                         -- URN d'acteur
      action  TEXT NOT NULL,                         -- 'proposal.accept', 'token.revoke'
      target  TEXT,                                  -- identifiants seulement
      outcome TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE collector_runs (
      id         TEXT PRIMARY KEY,
      collector  TEXT NOT NULL,
      started_at TEXT NOT NULL,
      ended_at   TEXT,
      outcome    TEXT CHECK (outcome IN ('ok','nothing_new','auth_pending_timeout',
                   'selector_missing','invalid_file','auth_error','site_unavailable','unknown')),
      files      INTEGER NOT NULL DEFAULT 0,
      detail     TEXT                                -- étape et sélecteur, jamais de contenu
    )
    """,
    """
    CREATE TABLE collector_state (
      collector            TEXT PRIMARY KEY,
      mode                 TEXT NOT NULL CHECK (mode IN ('enabled','degraded','disabled')),
      consecutive_failures INTEGER NOT NULL DEFAULT 0,
      since                TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE links (                             -- liens entre domaines, ajout seul
      seq         INTEGER PRIMARY KEY,
      from_urn    TEXT NOT NULL,
      to_urn      TEXT NOT NULL,
      rel         TEXT NOT NULL,
      active      INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
      proposal_id TEXT,
      created_by  TEXT NOT NULL,
      created_at  TEXT NOT NULL
    )
    """,
    "CREATE INDEX links_from ON links(from_urn)",
    "CREATE INDEX links_to ON links(to_urn)",
    """
    CREATE TABLE approval_policies (
      domain          TEXT NOT NULL,
      kind            TEXT NOT NULL,
      tier            TEXT NOT NULL CHECK (tier IN ('human','auto_digest','auto')),
      conditions_json TEXT NOT NULL DEFAULT '{}',
      PRIMARY KEY (domain, kind)
    )
    """,
    """
    CREATE TABLE webauthn_challenges (               -- défis en base, jamais en mémoire
      id           TEXT PRIMARY KEY,
      purpose      TEXT NOT NULL CHECK (purpose IN ('register','login','approve')),
      challenge    BLOB NOT NULL,
      bound_digest TEXT,
      expires_at   TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE rate_limits (
      actor        TEXT NOT NULL,
      window_start TEXT NOT NULL,
      count        INTEGER NOT NULL,
      PRIMARY KEY (actor, window_start)
    )
    """,
    """
    CREATE TABLE event_cursors (                     -- position de chaque consommateur d'événements
      consumer   TEXT NOT NULL,
      domain     TEXT NOT NULL,
      cursor     INTEGER NOT NULL DEFAULT 0,
      updated_at TEXT NOT NULL,
      PRIMARY KEY (consumer, domain)
    )
    """,
]


def _append_only(table: str) -> list[str]:
    return [
        f"CREATE TRIGGER {table}_no_update BEFORE UPDATE ON {table} "
        "BEGIN SELECT RAISE(ABORT, 'ledger.append_only'); END",
        f"CREATE TRIGGER {table}_no_delete BEFORE DELETE ON {table} "
        "BEGIN SELECT RAISE(ABORT, 'ledger.append_only'); END",
    ]


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)
    for table in PROTECTED:
        for trigger in _append_only(table):
            op.execute(trigger)


def downgrade() -> None:
    raise NotImplementedError("pas de retour arrière : restaurer la sauvegarde")
