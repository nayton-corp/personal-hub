"""Propositions sur les mouvements crypto (audit C1) : `link_crypto_moves` relie deux
mouvements (virement entre mes comptes, ou sortie de staking et son claim) ; son inverse
`unlink_crypto_moves` retire le lien par une ligne de retrait. Le hub propose (crypto_pairing.py),
l'assistant peut proposer ; toi seul valides."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import Connection

from hub.core.domain import Preview
from hub.domains.finance.patrimoine.app import crypto_moves
from hub.domains.finance.registre.app import ledger
from hub.domains.finance.registre.app.kinds import Host, Params, RefreshAfter, bad, fp
from hub.kernel.ids import urn

SAID = {"transfer": "virement entre mes comptes", "stake": "sortie de staking et son claim"}


EntryId = Annotated[str, Field(min_length=1, max_length=80)]


class LinkCryptoMoves(Params):
    """Deux écritures par leur identifiant stable (le même après une reconstruction)."""

    entry_id: EntryId  # l'arrivée (virement) ou l'envoi (staking)
    peer_id: EntryId  # l'envoi (virement) ou le claim (staking)
    kind: Literal["transfer", "stake"]


class LinkCryptoMovesHandler(RefreshAfter):
    def __init__(self, domain: Host) -> None:
        super().__init__(domain)

    def _pair(
        self, conn: Connection, params: LinkCryptoMoves
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        if params.entry_id == params.peer_id:
            raise bad("un mouvement ne se relie pas à lui-même")
        a, b = crypto_moves.brief(conn, params.entry_id), crypto_moves.brief(conn, params.peer_id)
        if a["asset"] != b["asset"]:
            raise bad("deux cryptos différentes")
        if crypto_moves.linked(conn, a["entry_seq"]):
            raise bad("mouvement déjà relié")
        if params.kind == "transfer":
            if crypto_moves.linked(conn, b["entry_seq"]):
                raise bad("mouvement déjà relié")
            if (a["role"], b["role"]) != ("in", "out") or a["account"] == b["account"]:
                raise bad("un virement relie une arrivée à un envoi d'un autre compte")
            return a, b
        # le claim porte déjà son lien de staking (écrit à l'import) : il ne doit pas déjà
        # expliquer une autre sortie
        if crypto_moves.linked(conn, b["entry_seq"], as_peer=True):
            raise bad("claim déjà relié à une sortie")
        if (a["role"], b["role"]) != ("out", "in") or a["account"] != b["account"]:
            raise bad("une sortie de staking relie un envoi au claim du même compte")
        return a, b

    def preview(self, conn: Connection, params: BaseModel) -> Preview:
        assert isinstance(params, LinkCryptoMoves)  # noqa: S101
        a, b = self._pair(conn, params)
        sent, got = str(b["quantity"]).lstrip("-"), str(a["quantity"]).lstrip("-")
        if params.kind == "transfer":
            summary = (
                f"Virement entre mes comptes : {sent} {b['asset']} envoyés de {b['account']} le "
                f"{b['on_date']}, {got} arrivés sur {a['account']} le {a['on_date']}"
            )
        else:
            summary = (
                f"Sortie de staking : {got} {a['asset']} sortis de {a['account']} le "
                f"{a['on_date']}, {sent} réclamés le {b['on_date']}"
            )
        return Preview(
            summary=summary,
            details={"kind": params.kind, "move": a, "peer": b, "said": SAID[params.kind]},
            fingerprint=fp("link_crypto_moves", params.entry_id, params.peer_id, params.kind),
        )

    def apply(self, conn: Connection, params: BaseModel, proposal_id: str) -> dict[str, Any]:
        assert isinstance(params, LinkCryptoMoves)  # noqa: S101
        a, b = self._pair(conn, params)
        method = "window" if params.kind == "transfer" else "claim"
        link_id = crypto_moves.link(
            conn,
            a["entry_seq"],
            params.kind,
            b["entry_seq"],
            method,
            actor="proposal",
            proposal_id=proposal_id,
        )
        changed(conn, a["entry_seq"])
        return {
            "link_id": link_id,
            "kind": params.kind,
            "entry_id": params.entry_id,
            "peer_id": params.peer_id,
        }


def changed(conn: Connection, entry_seq: int) -> None:
    """Un lien change le prix de revient et la performance : les instantanés se recalculent
    (snapshots.TRIGGERS), et les liens à deviner sont redemandés."""
    ledger.append_event(conn, "crypto.linked", urn("finance", "entry", str(entry_seq)))


def link_inverse(params: dict[str, Any], result: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    return "unlink_crypto_moves", {
        "entry_id": str(params["entry_id"]),
        "peer_id": str(params["peer_id"]),
        "kind": str(params["kind"]),
    }


class UnlinkCryptoMoves(Params):
    """Le lien actif entre deux écritures, désigné par la paire (rejouable après une
    reconstruction, où les identifiants de lien changent)."""

    entry_id: EntryId
    peer_id: EntryId
    kind: Literal["transfer", "stake"]


def _active(conn: Connection, params: UnlinkCryptoMoves) -> tuple[str, int]:
    a = crypto_moves.brief(conn, params.entry_id)
    b = crypto_moves.brief(conn, params.peer_id)
    link_id = crypto_moves.active_link(conn, a["entry_seq"], params.kind, b["entry_seq"])
    if link_id is None:
        raise bad("lien inconnu ou déjà retiré")
    return link_id, a["entry_seq"]


class UnlinkCryptoMovesHandler(RefreshAfter):
    def __init__(self, domain: Host) -> None:
        super().__init__(domain)

    def preview(self, conn: Connection, params: BaseModel) -> Preview:
        assert isinstance(params, UnlinkCryptoMoves)  # noqa: S101
        link_id, _seq = _active(conn, params)
        return Preview(
            summary=f"Retire le lien « {SAID[params.kind]} » : les deux mouvements redeviennent "
            "hors de mes comptes",
            details={"link_id": link_id, "kind": params.kind},
            fingerprint=fp("unlink_crypto_moves", params.entry_id, params.peer_id, params.kind),
        )

    def apply(self, conn: Connection, params: BaseModel, proposal_id: str) -> dict[str, Any]:
        assert isinstance(params, UnlinkCryptoMoves)  # noqa: S101
        link_id, seq = _active(conn, params)
        crypto_moves.withdraw(conn, link_id, actor="proposal", proposal_id=proposal_id)
        changed(conn, seq)
        return {"link_id": link_id}
