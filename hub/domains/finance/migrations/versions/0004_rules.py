"""finance.db : catégories et règles de départ reprises de `bcf_aggregate.py` (ticket L3-01).

Les catégories de l'ancien script qui manquaient sont ajoutées, trois noms sont alignés sur
ceux du script, et son fichier de départ devient des règles « seed- » à priorité explicite.

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

CREATED_AT = "2026-10-27T00:00:00.000Z"
RENAMED = {
    "restaurants": "Restaurants et sorties",
    "loisirs": "Loisirs et sport",
    "voyages": "Vacances",
}


def upgrade() -> None:
    conn = op.get_bind()
    specs, needed = legacy.convert(legacy.DEFAULT_RULES)
    for c in needed:
        conn.execute(
            text("INSERT OR IGNORE INTO categories (id, name, grp) VALUES (:i, :n, :g)"),
            {"i": c.id, "n": c.name, "g": c.grp},
        )
    for cid, name in RENAMED.items():
        conn.execute(text("UPDATE categories SET name = :n WHERE id = :i"), {"n": name, "i": cid})
    for s in specs:
        conn.execute(
            text(
                "INSERT INTO rules (id, field, pattern, direction, category_id, priority, "
                "created_at) VALUES (:id, :f, :p, :d, :c, :prio, :at)"
            ),
            {
                "id": s.id("seed"),
                "f": s.field,
                "p": s.pattern,
                "d": s.direction,
                "c": s.category_id,
                "prio": s.priority,
                "at": CREATED_AT,
            },
        )
    conn.execute(text("UPDATE rules_meta SET version = version + 1"))


def downgrade() -> None:
    raise NotImplementedError("pas de retour arrière : restaurer la sauvegarde")
