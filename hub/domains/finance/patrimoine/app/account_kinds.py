"""Propositions sur un compte : son but (épargne de sécurité, projets, long terme…) et ses
réglages (nom, disponibilité, catégorie de ses sorties, masqué)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import Connection, text

from hub.core.domain import Preview
from hub.domains.finance.registre.app.kinds import (
    Params,
    bad,
    fp,
)

if TYPE_CHECKING:
    pass


GOAL_LABEL = {
    "current": "Courant",
    "safety": "Réserve de sécurité",
    "projects": "Projets",
    "long_term": "Long terme",
    "retirement": "Retraite",
}


class SetAccountGoal(Params):
    account_id: str = Field(min_length=1, max_length=40)
    goal: Literal["current", "safety", "projects", "long_term", "retirement"]


class SetAccountGoalHandler:
    def _row(self, conn: Connection, account_id: str) -> Any:
        row = conn.execute(
            text("SELECT institution, name, goal FROM accounts WHERE id = :a"), {"a": account_id}
        ).first()
        if row is None:
            raise bad("compte inconnu")
        return row

    def preview(self, conn: Connection, params: BaseModel) -> Preview:
        assert isinstance(params, SetAccountGoal)  # noqa: S101
        row = self._row(conn, params.account_id)
        before = f" (avant {GOAL_LABEL[row[2]]})" if row[2] else ""
        return Preview(
            summary=f"Objectif de {row[0]} « {row[1]} » : {GOAL_LABEL[params.goal]}{before}",
            details={"account_id": params.account_id, "goal": params.goal, "previous": row[2]},
            fingerprint=fp("set_account_goal", params.account_id, row[2]),
        )

    def apply(self, conn: Connection, params: BaseModel, proposal_id: str) -> dict[str, Any]:
        assert isinstance(params, SetAccountGoal)  # noqa: S101
        previous = self._row(conn, params.account_id)[2]
        conn.execute(
            text("UPDATE accounts SET goal = :g WHERE id = :a"),
            {"g": params.goal, "a": params.account_id},
        )
        return {"account_id": params.account_id, "previous": previous}


AVAILABILITY_LABEL = {"immediate": "immédiate", "days": "sous quelques jours", "locked": "bloquée"}
CATEGORY_LABEL = {"cash": "Liquidités", "funds": "Actions et fonds", "crypto": "Crypto"}


class EditAccount(Params):
    """Réglages d'un compte dans l'app ; un champ absent ne change pas, « auto » rend la
    déduction par type de compte."""

    account_id: str = Field(min_length=1, max_length=40)
    name: str | None = Field(default=None, min_length=1, max_length=60)
    goal: Literal["current", "safety", "projects", "long_term", "retirement"] | None = None
    availability: Literal["auto", "immediate", "days", "locked"] | None = None
    category: Literal["auto", "cash", "funds", "crypto"] | None = None
    hidden: bool | None = None


class EditAccountHandler:
    COLS = ("name", "goal", "availability", "category", "hidden")

    def _row(self, conn: Connection, account_id: str) -> dict[str, Any]:
        row = conn.execute(
            text(
                "SELECT institution, name, goal, availability, category, hidden "
                "FROM accounts WHERE id = :a"
            ),
            {"a": account_id},
        ).first()
        if row is None:
            raise bad("compte inconnu")
        return {"institution": row[0], **dict(zip(self.COLS, row[1:], strict=True))}

    def _changes(self, row: dict[str, Any], p: EditAccount) -> dict[str, Any]:
        wanted: dict[str, Any] = {
            "name": p.name.strip() if p.name is not None else None,
            "goal": p.goal,
            "availability": p.availability,
            "category": p.category,
            "hidden": None if p.hidden is None else int(p.hidden),
        }
        out = {}
        for col, v in wanted.items():
            if v is None:
                continue
            value = None if v == "auto" else v
            if col == "name" and not value:
                raise bad("nom vide")
            if value != row[col]:
                out[col] = value
        if not out:
            raise bad("aucun changement")
        return out

    @staticmethod
    def _say(col: str, v: Any) -> str:
        if col == "name":
            return f"nom « {v} »"
        if col == "goal":
            return f"objectif {GOAL_LABEL[v].lower()}"
        if col == "availability":
            return f"disponibilité {AVAILABILITY_LABEL[v]}" if v else "disponibilité déduite"
        if col == "category":
            return f"catégorie {CATEGORY_LABEL[v].lower()}" if v else "catégorie déduite"
        return "masqué" if v else "affiché"

    def preview(self, conn: Connection, params: BaseModel) -> Preview:
        assert isinstance(params, EditAccount)  # noqa: S101
        row = self._row(conn, params.account_id)
        changes = self._changes(row, params)
        said = ", ".join(self._say(c, v) for c, v in changes.items())
        return Preview(
            summary=f"Compte {row['institution']} « {row['name']} » : {said}",
            details={"account_id": params.account_id, "changes": changes},
            fingerprint=fp("edit_account", params.account_id, [row[c] for c in self.COLS]),
        )

    def apply(self, conn: Connection, params: BaseModel, proposal_id: str) -> dict[str, Any]:
        assert isinstance(params, EditAccount)  # noqa: S101
        row = self._row(conn, params.account_id)
        changes = self._changes(row, params)
        sets = ", ".join(f"{c} = :{c}" for c in changes)  # noms tirés de COLS, jamais du client
        conn.execute(
            text(f"UPDATE accounts SET {sets} WHERE id = :a"),
            {**changes, "a": params.account_id},
        )
        return {"account_id": params.account_id, "previous": {c: row[c] for c in changes}}
