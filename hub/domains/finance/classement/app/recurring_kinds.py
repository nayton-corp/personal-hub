"""Corriger un abonnement repéré : le renommer, changer sa catégorie, ou le retirer (« ce n'est
pas un abonnement ») et le remettre. La détection (recurring.py) se trompe parfois ; ces choix
survivent à chaque recalcul. En ajout seul dans `recurring_choices`, le dernier choix d'une clé
fait foi ; `v_recurring` les applique."""

from __future__ import annotations

from pydantic import BaseModel, Field
from sqlalchemy import Connection, text

from hub.core.domain import Preview
from hub.domains.finance.classement.app.insights import EXPENSE_GROUPS
from hub.domains.finance.registre.app.kinds import Params, Slug, bad, category_row, fp
from hub.kernel.clock import now_iso


class SetRecurring(Params):
    key: str = Field(min_length=1, max_length=200)
    hidden: bool = False  # True : ce n'est pas un abonnement, retiré du budget
    label: str | None = Field(default=None, min_length=1, max_length=80)  # None : nom repéré
    category_id: Slug | None = None  # None : la catégorie du dernier paiement


def current(conn: Connection, key: str) -> tuple[int, dict[str, object]]:
    """Le dernier choix d'une clé (son numéro, 0 sans choix) et son état."""
    row = conn.execute(
        text(
            "SELECT seq, hidden, label, category_id FROM recurring_choices WHERE key = :k "
            "ORDER BY seq DESC LIMIT 1"
        ),
        {"k": key},
    ).first()
    if row is None:
        return 0, {"hidden": False, "label": None, "category_id": None}
    return int(row[0]), {"hidden": bool(row[1]), "label": row[2], "category_id": row[3]}


def _found(conn: Connection, key: str) -> str:
    row = conn.execute(text("SELECT label FROM recurring WHERE key = :k"), {"k": key}).first()
    if row is None and current(conn, key)[0] == 0:
        raise bad("abonnement inconnu : relance la recherche des abonnements")
    return str(row[0]) if row is not None else key.split("|")[0]


class SetRecurringHandler:
    def _check(self, conn: Connection, params: SetRecurring) -> str:
        name = _found(conn, params.key)
        if params.category_id is not None:
            _cat, grp = category_row(conn, params.category_id)
            if grp not in EXPENSE_GROUPS:
                raise bad(f"{params.category_id} n'est pas une catégorie de dépense")
        return params.label or name

    def preview(self, conn: Connection, params: BaseModel) -> Preview:
        assert isinstance(params, SetRecurring)  # noqa: S101
        name = self._check(conn, params)
        seq, before = current(conn, params.key)
        if params.hidden:
            summary = f"Retirer « {name} » des abonnements : ce n'est pas un abonnement"
        elif before["hidden"]:
            summary = f"Remettre « {name} » dans les abonnements"
        else:
            summary = f"Abonnement « {name} »" + (
                f", catégorie {params.category_id}" if params.category_id else ""
            )
        return Preview(
            summary=summary,
            details={"key": params.key, "previous": before},
            fingerprint=fp("set_recurring", params.key, seq),
        )

    def apply(self, conn: Connection, params: BaseModel, proposal_id: str) -> dict[str, object]:
        assert isinstance(params, SetRecurring)  # noqa: S101
        self._check(conn, params)
        _seq, before = current(conn, params.key)
        conn.execute(
            text(
                "INSERT INTO recurring_choices (key, hidden, label, category_id, proposal_id, "
                "created_at) VALUES (:k, :h, :l, :c, :p, :at)"
            ),
            {
                "k": params.key,
                "h": int(params.hidden),
                "l": params.label,
                "c": params.category_id,
                "p": proposal_id,
                "at": now_iso(),
            },
        )
        return {"previous": before}


def recurring_inverse(
    params: dict[str, object], result: dict[str, object]
) -> tuple[str, dict[str, object]]:
    before = result.get("previous")
    state = before if isinstance(before, dict) else {}
    return "set_recurring", {
        "key": params["key"],
        "hidden": bool(state.get("hidden")),
        "label": state.get("label"),
        "category_id": state.get("category_id"),
    }
