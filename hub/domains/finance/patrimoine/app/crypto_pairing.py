"""Ce que les mouvements crypto non reliés laissent deviner, proposé à ta validation (audit C1) :

- un envoi et une arrivée de la même crypto entre deux de mes comptes, à quelques jours
  (`WINDOW_DAYS` avant, `SLACK_DAYS` après) et à frais de retrait près (l'arrivée reçoit au plus
  5 % de moins) : un virement entre mes comptes ;
- un envoi sans marque suivi, dans les 60 jours, d'un claim de staking du même compte qui rend
  entre 100 % et 125 % de la mise : une sortie de staking, les parts n'ont jamais quitté mes
  comptes.

Avant R5, ces règles s'appliquaient à la lecture, sans trace ; elles ne font plus que demander
une carte `link_crypto_moves` (création idempotente par le cœur). Tant qu'elle attend, le
mouvement reste « hors de mes comptes » dans le prix de revient et le rapprochement.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import Connection

from hub.domains.finance.patrimoine.app import crypto_moves
from hub.domains.finance.patrimoine.app.links import SLACK_DAYS, WINDOW_DAYS
from hub.domains.finance.registre.app import ledger
from hub.kernel.ids import urn

TRANSFER_FEE = Decimal("0.05")  # part d'un virement que les frais de retrait peuvent prendre
STAKE_DAYS = 60  # d'une demande de sortie de staking à son claim
STAKE_GAIN = Decimal("1.25")  # le claim rend la mise et ses récompenses, pas plus
KIND = "link_crypto_moves"


@dataclass(frozen=True)
class Candidate:
    kind: str  # transfer | stake
    entry_seq: int  # l'arrivée (virement) ou l'envoi (sortie de staking)
    peer_seq: int  # l'envoi (virement) ou le claim (staking)
    reason: str
    entry_id: str = ""  # identifiants stables des mêmes écritures, pour la carte
    peer_id: str = ""


def _stakes(found: list[crypto_moves.Move]) -> list[Candidate]:
    out = []
    taken: set[int] = set()
    for i, claim in enumerate(found):
        if claim.role != "stake" or claim.quantity <= 0:
            continue
        start = (date.fromisoformat(claim.on) - timedelta(days=STAKE_DAYS)).isoformat()
        for j in range(i - 1, -1, -1):
            sent = found[j]
            if sent.on < start:
                break
            if sent.seq in taken or sent.internal or sent.role != "out":
                continue
            if (sent.symbol, sent.account_id) != (claim.symbol, claim.account_id):
                continue
            if -sent.quantity <= claim.quantity <= -sent.quantity * STAKE_GAIN:
                taken.add(sent.seq)
                out.append(
                    Candidate(
                        "stake",
                        sent.seq,
                        claim.seq,
                        f"envoi de {sent.symbol} du {sent.on} suivi d'un claim le {claim.on}",
                        sent.entry_id,
                        claim.entry_id,
                    )
                )
                break
    return out


def _transfers(found: list[crypto_moves.Move], taken: set[int]) -> list[Candidate]:
    out = []
    for arrived in found:
        if arrived.role != "in" or arrived.internal or arrived.quantity <= 0:
            continue
        day = date.fromisoformat(arrived.on)
        start = (day - timedelta(days=WINDOW_DAYS)).isoformat()
        end = (day + timedelta(days=SLACK_DAYS)).isoformat()
        best: tuple[int, Decimal, crypto_moves.Move] | None = None
        for sent in found:
            if sent.role != "out" or sent.internal or sent.seq in taken:
                continue
            if sent.symbol != arrived.symbol or sent.account_id == arrived.account_id:
                continue
            if not start <= sent.on <= end:
                continue
            if -sent.quantity * (1 - TRANSFER_FEE) <= arrived.quantity <= -sent.quantity:
                gap = abs((date.fromisoformat(sent.on) - day).days)
                lost = -sent.quantity - arrived.quantity
                if best is None or (gap, lost) < best[:2]:
                    best = (gap, lost, sent)
        if best is not None:
            taken.add(best[2].seq)
            out.append(
                Candidate(
                    "transfer",
                    arrived.seq,
                    best[2].seq,
                    f"envoi de {arrived.symbol} le {best[2].on}, arrivée le {arrived.on}",
                    arrived.entry_id,
                    best[2].entry_id,
                )
            )
    return out


def candidates(found: list[crypto_moves.Move]) -> list[Candidate]:
    """Les liens que les mouvements non reliés laissent deviner, sorties de staking d'abord."""
    stakes = _stakes(found)
    taken = {c.entry_seq for c in stakes}
    return stakes + _transfers(found, taken)


def request(conn: Connection, on_date: str) -> int:
    """Demande au cœur une carte par lien deviné ; renvoie le nombre de demandes."""
    found = candidates(crypto_moves.moves(conn, on_date))
    for c in found:
        ledger.append_event(
            conn,
            "proposal.request",
            urn("finance", "entry", str(c.entry_seq)),
            {
                "kind": KIND,
                "params": {"entry_id": c.entry_id, "peer_id": c.peer_id, "kind": c.kind},
                "reason": c.reason,
            },
        )
    return len(found)
