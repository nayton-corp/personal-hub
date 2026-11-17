"""Gérer les catégories (refonte du budget, lot Q) : renommer, changer d'icône, de groupe ou de
mode, fusionner deux catégories, archiver et restaurer. L'identifiant ne change jamais, et
l'historique reste juste :

- un changement de groupe ne se fait que si aucun mois clos n'a d'écriture dans la catégorie
  (le groupe n'est pas daté : il réécrirait les mois clos) ; sinon, en créer une autre ;
- une fusion ne réunit que deux catégories du même groupe : les écritures (ventilations
  comprises), les règles et la cible passent sur la catégorie gardée, l'autre est archivée ;
  les totaux d'un mois clos ne bougent pas ;
- une catégorie archivée sort des listes et du classement (ses règles ne classent plus), son
  historique reste ; elle se restaure d'un geste.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol

from pydantic import BaseModel, Field
from sqlalchemy import Connection, text

from hub.core.domain import Preview
from hub.domains.finance.classement.app import rules
from hub.domains.finance.classement.app.insights import Target, target_of
from hub.domains.finance.registre.app import ledger
from hub.domains.finance.registre.app.entry_kinds import Icon, Mode
from hub.domains.finance.registre.app.kinds import Params, RefreshAfter, Slug, bad, fp
from hub.domains.finance.registre.model import period
from hub.kernel.clock import now_iso
from hub.kernel.money import base_currency

GROUP_NAMES = {
    "fixed": "fixes",
    "variable": "variables",
    "savings": "épargne",
    "income": "revenus",
    "transfer": "virements",
}
MODE_NAMES = {"target": "avec cible", "tracked": "suivie sans cible", "off_budget": "hors budget"}


class Host(Protocol):
    def today(self) -> date: ...
    def refresh_snapshots(self) -> object: ...


@dataclass(frozen=True)
class Cat:
    id: str
    name: str
    grp: str
    active: bool
    mode: str | None
    icon: str | None


def _row(conn: Connection, category_id: str) -> Cat:
    row = conn.execute(
        text("SELECT id, name, grp, active, mode, icon FROM categories WHERE id = :c"),
        {"c": category_id},
    ).first()
    if row is None:
        raise bad(f"catégorie inconnue : {category_id}")
    return Cat(str(row[0]), str(row[1]), str(row[2]), bool(row[3]), row[4], row[5])


def _state(row: Cat) -> list[object]:
    return [row.name, row.grp, row.active, row.mode, row.icon]


class EditCategory(Params):
    category_id: Slug
    name: str | None = Field(default=None, min_length=1, max_length=60)
    icon: Icon | None = None
    grp: str | None = Field(default=None, pattern=r"^(fixed|variable|savings|income)$")
    mode: Mode | None = None


def _closed_entries(conn: Connection, category_id: str, today: date) -> int:
    start, _ = period.bounds(period.month_of(today))
    return int(
        conn.execute(
            text(
                "SELECT count(*) FROM v_entry_allocation "
                "WHERE category_id = :c AND booking_date < :s"
            ),
            {"c": category_id, "s": start.isoformat()},
        ).scalar_one()
    )


class EditCategoryHandler:
    def __init__(self, domain: Host) -> None:
        self.domain = domain

    def preview(self, conn: Connection, params: BaseModel) -> Preview:
        assert isinstance(params, EditCategory)  # noqa: S101
        row = _row(conn, params.category_id)
        if row.grp == "transfer":
            raise bad("les virements entre mes comptes ne se modifient pas")
        said = []
        if params.name is not None and params.name != row.name:
            said.append(f"nom « {params.name} »")
        if params.icon is not None and params.icon != row.icon:
            said.append("nouvelle icône")
        if params.grp is not None and params.grp != row.grp:
            if _closed_entries(conn, params.category_id, self.domain.today()):
                raise bad(
                    "des mois clos ont des écritures dans cette catégorie : changer son groupe "
                    "réécrirait leurs chiffres ; crée plutôt une catégorie dans l'autre groupe"
                )
            said.append(f"groupe {GROUP_NAMES[params.grp]}")
        if params.mode is not None and params.mode != row.mode:
            said.append(MODE_NAMES[params.mode])
        if not said:
            raise bad("rien ne change")
        return Preview(
            summary=f"Catégorie {row.name} : {', '.join(said)}",
            details={**params.model_dump(), "previous": {"name": row.name, "grp": row.grp}},
            fingerprint=fp("edit_category", params.category_id, *_state(row)),
        )

    def apply(self, conn: Connection, params: BaseModel, proposal_id: str) -> dict[str, object]:
        assert isinstance(params, EditCategory)  # noqa: S101
        row = _row(conn, params.category_id)
        conn.execute(
            text("UPDATE categories SET name = :n, grp = :g, mode = :m, icon = :i WHERE id = :c"),
            {
                "n": params.name or row.name,
                "g": params.grp or row.grp,
                "m": params.mode or row.mode,
                "i": params.icon or row.icon,
                "c": params.category_id,
            },
        )
        return {"previous": {"name": row.name, "grp": row.grp, "mode": row.mode, "icon": row.icon}}


def edit_inverse(
    params: dict[str, object], result: dict[str, object]
) -> tuple[str, dict[str, object]]:
    found = result.get("previous")
    before = found if isinstance(found, dict) else {}
    return "edit_category", {
        "category_id": params["category_id"],
        **{k: before.get(k) for k in ("name", "icon", "grp", "mode") if params.get(k) is not None},
    }


# --- fusionner ----------------------------------------------------------------------------------


class MergeCategories(Params):
    from_id: Slug  # celle qui disparaît (archivée)
    into_id: Slug  # celle qu'on garde


def _entries_of(conn: Connection, category_id: str) -> list[tuple[int, int, str]]:
    """Les catégorisations en vigueur qui citent la catégorie (en principal ou dans une ligne)."""
    rows = conn.execute(
        text(
            "SELECT DISTINCT vc.entry_seq, vc.categorization_seq, vc.category_id "
            "FROM v_entry_category vc LEFT JOIN categorization_lines l "
            "ON l.categorization_seq = vc.categorization_seq "
            "WHERE vc.category_id = :c OR l.category_id = :c ORDER BY vc.entry_seq"
        ),
        {"c": category_id},
    )
    return [(int(r[0]), int(r[1]), str(r[2])) for r in rows]


def _merged_target(conn: Connection, a: str, b: str) -> Target | None:
    """La cible de la catégorie gardée après fusion : la somme des deux, à la cadence commune,
    sinon au mois ; None si aucune n'en a."""
    found = []
    for cat in (a, b):
        row = conn.execute(
            text(
                "SELECT b.monthly_minor, b.amount_minor, b.cadence, c.cadence FROM budgets b "
                "LEFT JOIN budget_cadence c ON c.category_id = b.category_id "
                "WHERE b.category_id = :c ORDER BY b.seq DESC LIMIT 1"
            ),
            {"c": cat},
        ).first()
        if row is not None:
            t = target_of(row[0], row[1], row[2], row[3])
            if t.amount > 0:
                found.append(t)
    if not found:
        return None
    if len({t.cadence for t in found}) == 1:
        return Target(sum(t.amount for t in found), found[0].cadence)
    return Target(sum(t.monthly for t in found), "month")


class MergeCategoriesHandler(RefreshAfter):
    def __init__(self, domain: Host) -> None:
        super().__init__(domain)
        self.host = domain

    def _check(self, conn: Connection, params: MergeCategories) -> tuple[Cat, Cat]:
        if params.from_id == params.into_id:
            raise bad("deux catégories différentes, s'il te plaît")
        a, b = _row(conn, params.from_id), _row(conn, params.into_id)
        if not b.active:
            raise bad(f"{b.name} est archivée : la restaurer d'abord")
        if a.grp != b.grp or a.grp == "transfer":
            raise bad("seules deux catégories du même groupe se fusionnent")
        return a, b

    def preview(self, conn: Connection, params: BaseModel) -> Preview:
        assert isinstance(params, MergeCategories)  # noqa: S101
        a, b = self._check(conn, params)
        moved = _entries_of(conn, params.from_id)
        n_rules = int(
            conn.execute(
                text("SELECT count(*) FROM rules WHERE category_id = :c"), {"c": params.from_id}
            ).scalar_one()
        )
        n = len(moved)
        return Preview(
            summary=(
                f"Fusionner {a.name} dans {b.name} : {n} écriture{'s' if n > 1 else ''}, "
                f"{n_rules} règle{'s' if n_rules > 1 else ''} ; {a.name} est archivée"
            ),
            details={"from_id": a.id, "into_id": b.id, "entries": n, "rules": n_rules},
            fingerprint=fp(
                "merge_categories", a.id, b.id, *_state(a), *_state(b), [m[1] for m in moved]
            ),
        )

    def apply(self, conn: Connection, params: BaseModel, proposal_id: str) -> dict[str, object]:
        assert isinstance(params, MergeCategories)  # noqa: S101
        self._check(conn, params)
        old, new, at = params.from_id, params.into_id, now_iso()
        moved = _entries_of(conn, old)
        for entry_seq, cat_seq, main in moved:
            seq = ledger.append(
                conn,
                "categorizations",
                {
                    "entry_seq": entry_seq,
                    "category_id": new if main == old else main,
                    "source": "user",
                    "rule_id": None,
                    "proposal_id": proposal_id,
                    "created_at": at,
                },
            )
            lines = conn.execute(
                text(
                    "SELECT line, category_id, amount_minor FROM categorization_lines "
                    "WHERE categorization_seq = :s ORDER BY line"
                ),
                {"s": cat_seq},
            ).fetchall()
            for line, cat, amount in lines:
                ledger.append(
                    conn,
                    "categorization_lines",
                    {
                        "categorization_seq": seq,
                        "line": line,
                        "category_id": new if cat == old else cat,
                        "amount_minor": amount,
                    },
                )
        target = _merged_target(conn, old, new)
        valid_from = f"{period.month_of(self.host.today())}-01"
        if target is not None:
            for cat, t in ((new, target), (old, Target(0, "month"))):
                ledger.append(
                    conn,
                    "budgets",
                    {
                        "category_id": cat,
                        "monthly_minor": t.monthly,
                        "amount_minor": t.amount,
                        "cadence": t.cadence,
                        "currency": base_currency(),
                        "valid_from": valid_from,
                        "proposal_id": proposal_id,
                        "created_at": at,
                    },
                )
        n_rules = conn.execute(
            text("UPDATE rules SET category_id = :n WHERE category_id = :o"), {"n": new, "o": old}
        ).rowcount
        if n_rules:
            rules.bump_version(conn)
        conn.execute(
            text("UPDATE categories SET active = 0, archived_at = :at WHERE id = :c"),
            {"at": at, "c": old},
        )
        return {"entries": len(moved), "rules": n_rules, "archived": old}


# --- archiver -----------------------------------------------------------------------------------


class ArchiveCategory(Params):
    category_id: Slug
    archived: bool = True  # False : restaurer


class ArchiveCategoryHandler(RefreshAfter):
    def preview(self, conn: Connection, params: BaseModel) -> Preview:
        assert isinstance(params, ArchiveCategory)  # noqa: S101
        row = _row(conn, params.category_id)
        if row.grp == "transfer":
            raise bad("les virements entre mes comptes ne s'archivent pas")
        if bool(row.active) != params.archived:
            raise bad("déjà archivée" if params.archived else "pas archivée")
        what = "Archiver" if params.archived else "Restaurer"
        return Preview(
            summary=f"{what} la catégorie {row.name}",
            details=params.model_dump(),
            fingerprint=fp("archive_category", *_state(row)),
        )

    def apply(self, conn: Connection, params: BaseModel, proposal_id: str) -> dict[str, object]:
        assert isinstance(params, ArchiveCategory)  # noqa: S101
        conn.execute(
            text("UPDATE categories SET active = :a, archived_at = :at WHERE id = :c"),
            {
                "a": 0 if params.archived else 1,
                "at": now_iso() if params.archived else None,
                "c": params.category_id,
            },
        )
        rules.bump_version(conn)  # ses règles cessent (ou reprennent) de classer
        return {"category_id": params.category_id, "archived": params.archived}


def archive_inverse(
    params: dict[str, object], _result: dict[str, object]
) -> tuple[str, dict[str, object]]:
    return "archive_category", {
        "category_id": params["category_id"],
        "archived": not params.get("archived", True),
    }
