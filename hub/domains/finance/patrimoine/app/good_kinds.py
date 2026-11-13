"""Proposition sur les biens hors comptes : créer un bien, le modifier, réestimer sa valeur."""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Literal, Protocol

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import Connection, text

from hub.core.domain import Preview
from hub.domains.finance.patrimoine.app import goods
from hub.domains.finance.registre.app import ledger
from hub.domains.finance.registre.app.kinds import Params, bad, fp, shown_amount
from hub.kernel.clock import now_iso
from hub.kernel.ids import new_id, urn
from hub.kernel.money import base_currency


class Host(Protocol):
    """Ce que le handler attend du domaine (`FinanceDomain` le remplit)."""

    def refresh_snapshots(self) -> object: ...


DateStr = Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$")]
Clearable = Annotated[str, Field(pattern=r"^(\d{4}-\d{2}-\d{2})?$")]
# variation annuelle en % : « -15 » (perd 15 % par an), « 2.5 », « 0 » (valeur fixe)
ChangePct = Annotated[str, Field(pattern=r"^-?\d{1,2}(\.\d{1,2})?$")]
Amount = Annotated[int, Field(ge=0, le=100_000_000_000)]


class SaveGood(Params):
    """Crée un bien hors comptes (sans `good_id` : nom, genre, valeur et date requis) ou en
    change les champs donnés ; un champ absent ne change pas. Une valeur donnée avec sa date
    s'ajoute aux valeurs saisies : le calcul repart de là."""

    good_id: str | None = Field(default=None, min_length=1, max_length=40)
    name: str | None = Field(default=None, min_length=1, max_length=60)
    kind: Literal["home", "vehicle", "object", "loan", "other"] | None = None
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")  # à la création
    yearly_change_pct: ChangePct | None = None  # "0" : valeur fixe
    closed_on: Clearable | None = None  # "" : rouvert
    value_minor: Amount | None = None
    value_on: DateStr | None = None

    @model_validator(mode="after")
    def _check(self) -> SaveGood:
        if (self.value_minor is None) != (self.value_on is None):
            raise ValueError("valeur : value_minor et value_on vont ensemble")
        if self.good_id is None:
            missing = [f for f in ("name", "kind", "value_minor") if getattr(self, f) is None]
            if missing:
                raise ValueError(f"champs requis pour un nouveau bien : {', '.join(missing)}")
        elif self.currency is not None:
            raise ValueError("la devise se donne à la création")
        return self


class SaveGoodHandler:
    COLS = ("name", "kind", "currency", "yearly_change", "closed_on")

    def __init__(self, domain: Host) -> None:
        self.domain = domain

    def _row(self, conn: Connection, good_id: str) -> dict[str, object]:
        row = conn.execute(
            text(f"SELECT {', '.join(self.COLS)} FROM goods WHERE id = :i"), {"i": good_id}
        ).first()
        if row is None:
            raise bad("bien inconnu")
        return dict(zip(self.COLS, row, strict=True))

    @staticmethod
    def _wanted(conn: Connection, p: SaveGood) -> dict[str, object]:
        out: dict[str, object] = {}
        if p.name is not None:
            if not p.name.strip():
                raise bad("nom vide")
            out["name"] = p.name.strip()
        if p.kind is not None:
            out["kind"] = p.kind
        if p.currency is not None:
            known = conn.execute(
                text("SELECT 1 FROM currencies WHERE code = :c"), {"c": p.currency}
            ).first()
            if known is None:
                raise bad(f"devise inconnue : {p.currency}")
            out["currency"] = p.currency
        if p.yearly_change_pct is not None:
            change = Decimal(p.yearly_change_pct) / 100
            if change <= -1:
                raise bad("variation annuelle : au plus -99 %")
            out["yearly_change"] = format(change.normalize(), "f") if change else None
        if p.closed_on is not None:
            out["closed_on"] = p.closed_on or None
        return out

    def _changes(
        self, conn: Connection, p: SaveGood
    ) -> tuple[dict[str, object] | None, dict[str, object]]:
        wanted = self._wanted(conn, p)
        if p.good_id is None:
            wanted["currency"] = wanted.get("currency") or base_currency()
            return None, wanted
        row = self._row(conn, p.good_id)
        changes = {c: v for c, v in wanted.items() if v != row[c]}
        if not changes and p.value_minor is None:
            raise bad("aucun changement")
        return row, changes

    def preview(self, conn: Connection, params: BaseModel) -> Preview:
        assert isinstance(params, SaveGood)  # noqa: S101
        row, changes = self._changes(conn, params)
        ccy = str(changes["currency"] if row is None else row["currency"])
        worth = (
            f"{shown_amount(params.value_minor, ccy)} au {params.value_on}"
            if params.value_minor is not None
            else ""
        )
        if row is None:
            summary = (
                f"Nouveau bien « {changes['name']} » "
                f"({goods.KIND_LABEL[str(changes['kind'])]}) : {worth}"
            )
            digest = fp("save_good", "absent", changes["name"])
        else:
            parts = [f"{', '.join(sorted(changes))} modifiés"] if changes else []
            if worth:
                parts.append(f"valeur de {worth}")
            summary = f"Bien « {row['name']} » : {' ; '.join(parts)}"
            if changes.get("closed_on"):
                summary = f"Bien « {row['name']} » clos au {changes['closed_on']}"
            digest = fp("save_good", params.good_id, [row[c] for c in self.COLS], params.value_on)
        return Preview(
            summary=summary,
            details={"good_id": params.good_id, "changes": changes},
            fingerprint=digest,
        )

    def apply(self, conn: Connection, params: BaseModel, proposal_id: str) -> dict[str, object]:
        assert isinstance(params, SaveGood)  # noqa: S101
        row, changes = self._changes(conn, params)
        at = now_iso()
        if row is None:
            good_id = new_id()
            values = {c: changes.get(c) for c in self.COLS}
            conn.execute(
                text(
                    f"INSERT INTO goods (id, {', '.join(self.COLS)}, created_at, updated_at) "
                    f"VALUES (:id, {', '.join(':' + c for c in self.COLS)}, :at, :at)"
                ),
                {**values, "id": good_id, "at": at},
            )
            previous: dict[str, object] = {}
        else:
            good_id = str(params.good_id)
            if changes:
                sets = ", ".join(f"{c} = :{c}" for c in changes)  # noms tirés de COLS
                conn.execute(
                    text(f"UPDATE goods SET {sets}, updated_at = :at WHERE id = :i"),
                    {**changes, "at": at, "i": good_id},
                )
            previous = {c: row[c] for c in changes}
        if params.value_minor is not None and params.value_on is not None:
            goods.record_value(conn, good_id, params.value_on, params.value_minor, proposal_id)
        ledger.append_event(conn, "debt.changed", urn("finance", "good", good_id))
        return {"good_id": good_id, "previous": previous}

    def after_commit(self, params: BaseModel, result: dict[str, object]) -> None:
        self.domain.refresh_snapshots()
