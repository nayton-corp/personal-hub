"""core.db : connexions de l'instance (chantier « hub générique », G4).

Une connexion est l'usage d'un connecteur du catalogue (`hub/core/connectors.py`) : son
identifiant (nom d'état des runs, de la mémoire du collecteur et du retour de consentement), son
horaire, ses réglages sans secret et ses secrets, chiffrés par age vers la clé de la machine.
L'API les chiffre à la saisie et ne les relit jamais : seul le service collecteur qui exécute la
connexion les déchiffre, au moment du run.

Une base existante reçoit une connexion par collecteur déjà connu (`collector_state`), sans
secret : `hub connections import` les reprend des fichiers `<nom>.enc.yaml` des anciens
conteneurs. Le collecteur « revolut » devient une connexion « revolut » du connecteur
`enable_banking`.

Revision ID: 0004_connections
Revises: 0003_profile
Create Date: 2026-10-28
"""

import sqlalchemy as sa
from alembic import op

from hub.kernel.clock import now_iso

revision = "0004_connections"
down_revision = "0003_profile"
branch_labels = None
depends_on = None

# la banque de la connexion « revolut », implicite avant G4
REVOLUT = '{"aspsp_country": "LT", "aspsp_name": "Revolut"}'
# collecteurs d'avant G4 → (connecteur, nom affiché)
KNOWN = {
    "bcf": ("bcf", "BCF"),
    "viac": ("viac", "VIAC"),
    "revolut": ("enable_banking", "Revolut"),
    "ibkr": ("ibkr", "IBKR"),
    "market": ("market", "Cours et cryptos"),
    "binance": ("binance", "Binance"),
    "kucoin": ("kucoin", "KuCoin"),
    "coinbase": ("coinbase", "Coinbase"),
}


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE connections (
          id          TEXT PRIMARY KEY CHECK (length(id) BETWEEN 2 AND 40),
          connector   TEXT NOT NULL,                 -- entrée du catalogue
          label       TEXT NOT NULL CHECK (length(label) BETWEEN 1 AND 60),
          schedule    TEXT,                          -- cron ; NULL : horaire du catalogue
          settings    TEXT NOT NULL DEFAULT '{}',    -- JSON, sans secret
          secrets     BLOB,                          -- JSON chiffré age ; jamais relu par l'API
          secrets_at  TEXT,
          created_at  TEXT NOT NULL,
          updated_at  TEXT NOT NULL
        )
        """
    )
    conn = op.get_bind()
    at = now_iso()
    names = conn.execute(sa.text("SELECT collector FROM collector_state")).scalars().all()
    for name in names:
        if name not in KNOWN:
            continue
        connector, label = KNOWN[name]
        conn.execute(
            sa.text(
                "INSERT INTO connections (id, connector, label, settings, created_at, "
                "updated_at) VALUES (:id, :c, :l, :s, :at, :at)"
            ),
            {
                "id": name,
                "c": connector,
                "l": label,
                "s": REVOLUT if name == "revolut" else "{}",
                "at": at,
            },
        )


def downgrade() -> None:
    raise NotImplementedError("pas de retour arrière : restaurer la sauvegarde")
