"""finance.db : catégories reprises de `bcf_aggregate.py` (ticket L3-01).

Les catégories de l'ancien script qui manquaient sont ajoutées et trois noms sont alignés sur
ceux du script. Jusqu'au chantier « hub générique » (G2), cette révision installait aussi le
fichier de départ du script en règles « seed- » ; une base créée depuis reçoit ses règles des
packs (`hub/domains/finance/packs/`), une base plus ancienne garde les siennes.

Revision ID: 0004_rules
Revises: 0003_snapshots
Create Date: 2026-10-27
"""

from alembic import op
from sqlalchemy import text

from hub.domains.finance import legacy

revision = "0004_rules"
down_revision = "0003_snapshots"
branch_labels = None
depends_on = None

# comptes de l'ancien script, pas des catégories pour tout le monde
PERSONAL = frozenset({"transfer-revolut", "transfer-raiffeisen"})
RENAMED = {
    "restaurants": "Restaurants et sorties",
    "loisirs": "Loisirs et sport",
    "voyages": "Vacances",
}


def upgrade() -> None:
    conn = op.get_bind()
    needed = [*legacy.CATEGORY_MAP.values(), *legacy.TRANSFER_MAP.values()]
    for c_id, c_name, c_grp in needed:
        if c_id in PERSONAL:
            continue
        conn.execute(
            text("INSERT OR IGNORE INTO categories (id, name, grp) VALUES (:i, :n, :g)"),
            {"i": c_id, "n": c_name, "g": c_grp},
        )
    for cid, name in RENAMED.items():
        conn.execute(text("UPDATE categories SET name = :n WHERE id = :i"), {"n": name, "i": cid})
    conn.execute(text("UPDATE rules_meta SET version = version + 1"))


def downgrade() -> None:
    raise NotImplementedError("pas de retour arrière : restaurer la sauvegarde")
