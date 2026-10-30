"""Liens entre domaines (chantier S9) : le type de proposition `link` du cœur.

Un lien relie deux objets de domaines montés (un justificatif à une écriture, un objet à son
document). Il passe par une carte comme toute écriture : le cœur tient le type de proposition
`core/link` et son inverse `core/unlink`, appliqués dans `core.db` (`links`, en ajout seul :
délier ajoute une ligne `active = 0`). `owner()` donne aux propositions le propriétaire d'un
type : un domaine du registre, ou le cœur lui-même.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import Connection, Engine, text

from hub.core import integrity
from hub.core.auth import Principal
from hub.core.context import HubContext
from hub.core.domain import Domain, Preview, ProposalKind, Ref
from hub.core.errors import Problem
from hub.kernel import canonical
from hub.kernel.clock import now_iso
from hub.kernel.ids import Urn

CORE = "core"
REL = r"^[a-z][a-z_]{1,29}$"
LEDGER = integrity.Ledger(integrity.COMMON_FIELDS)


class LinkParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    from_urn: str = Field(max_length=200)
    to_urn: str = Field(max_length=200)
    rel: str = Field(default="about", pattern=REL)

    @field_validator("rel")
    @classmethod
    def _not_reserved(cls, value: str) -> str:
        if value == "reverts":  # réservé aux annulations (`proposals.revert`)
            raise ValueError("relation réservée")
        return value


def resolve(hub: HubContext, value: str) -> Ref | None:
    try:
        parsed = Urn.parse(value)
    except ValueError:
        return None
    if parsed.domain not in hub.registry.names():
        return None
    return hub.registry.get(parsed.domain).resolve(value)


def active(conn: Connection, p: LinkParams) -> bool:
    row = conn.execute(
        text(
            "SELECT active FROM links WHERE from_urn = :f AND to_urn = :t AND rel = :r "
            "ORDER BY seq DESC LIMIT 1"
        ),
        {"f": p.from_urn, "t": p.to_urn, "r": p.rel},
    ).first()
    return bool(row and row[0])


class _Handler:
    """`link` (want = True) et `unlink` (want = False) : l'aperçu nomme les deux objets."""

    def __init__(self, hub: HubContext, want: bool) -> None:
        self._hub = hub
        self._want = want

    def _refs(self, p: LinkParams) -> tuple[Ref, Ref]:
        if p.from_urn == p.to_urn:
            raise Problem("validation.params", "un objet ne se lie pas à lui-même")
        a, b = resolve(self._hub, p.from_urn), resolve(self._hub, p.to_urn)
        if a is None or b is None:
            raise Problem("validation.params", "objet introuvable")
        return a, b

    def preview(self, conn: Connection, params: BaseModel) -> Preview:
        p = LinkParams.model_validate(params.model_dump())
        a, b = self._refs(p)
        now = active(conn, p)
        verb = "Lier" if self._want else "Délier"
        return Preview(
            f"{verb} « {a.title} » et « {b.title} »",
            {"from": _ref(a), "to": _ref(b), "rel": p.rel, "active": now},
            canonical.sha256_hex({"link": p.model_dump(), "active": now}),
        )

    def apply(self, conn: Connection, params: BaseModel, proposal_id: str) -> dict[str, Any]:
        p = LinkParams.model_validate(params.model_dump())
        if active(conn, p) == self._want:
            raise Problem("validation.params", "déjà lié" if self._want else "déjà délié")
        seq = conn.execute(
            text(
                "INSERT INTO links (from_urn, to_urn, rel, active, proposal_id, created_by, "
                "created_at) VALUES (:f, :t, :r, :a, :p, 'system:hub', :at) RETURNING seq"
            ),
            {
                "f": p.from_urn,
                "t": p.to_urn,
                "r": p.rel,
                "a": int(self._want),
                "p": proposal_id,
                "at": now_iso(),
            },
        ).scalar_one()
        return {"seq": int(seq)}


def _ref(r: Ref) -> dict[str, Any]:
    return {"urn": r.urn, "title": r.title, "date": r.date, "href": r.href}


def _inverse(kind: str) -> Any:
    return lambda params, _result: (kind, params)


class CoreOwner:
    """Le cœur, propriétaire de ses propres types de proposition (`core.db`)."""

    name = CORE

    def __init__(self, hub: HubContext) -> None:
        self._hub = hub
        self.proposal_kinds: Mapping[str, ProposalKind] = {
            "link": ProposalKind(
                LinkParams,
                _Handler(hub, want=True),
                reversible=True,
                inverse=_inverse("unlink"),
                ai_allowed=True,
            ),
            "unlink": ProposalKind(
                LinkParams,
                _Handler(hub, want=False),
                reversible=True,
                inverse=_inverse("link"),
                ai_allowed=True,
            ),
        }

    def engine(self) -> Engine:
        return self._hub.core.engine

    def applied(self, proposal_ids: Sequence[str]) -> Mapping[str, dict[str, Any]]:
        with self.engine().connect() as conn:
            return integrity.applied(conn, proposal_ids)

    def record_applied(
        self, conn: Connection, proposal_id: str, kind: str, result: dict[str, Any]
    ) -> None:
        LEDGER.record_applied(conn, proposal_id, kind, result)


Owner = Domain | CoreOwner


def owner(hub: HubContext, name: str) -> Owner:
    return CoreOwner(hub) if name == CORE else hub.registry.get(name)


def owners(hub: HubContext) -> Iterator[Owner]:
    yield CoreOwner(hub)
    yield from hub.registry


def authorize(hub: HubContext, principal: Principal, params: dict[str, Any]) -> None:
    """Un jeton ne lie que des objets qu'il peut lire : sinon l'aperçu lui en montrerait le
    titre."""
    if principal.is_app:
        return
    for key in ("from_urn", "to_urn"):
        try:
            domain = Urn.parse(str(params.get(key, ""))).domain
        except ValueError:
            raise Problem("validation.params", "URN invalide") from None
        if not principal.allows(f"{domain}:read"):
            raise Problem("auth.scope")
