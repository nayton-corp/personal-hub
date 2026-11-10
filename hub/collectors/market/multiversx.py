"""MultiversX (EGLD) : solde (disponible, délégué, en retrait, récompenses à réclamer) et
historique par l'API publique MultiversX (sans clé)."""

from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from hub.collectors.base import Failure
from hub.collectors.http import Http
from hub.collectors.market import net
from hub.collectors.runtime import Env

if TYPE_CHECKING:
    from hub.collectors.market.history import Move

ADDRESS = re.compile(r"erd1[02-9ac-hj-np-z]{58}")
PAGES = 20  # pages de 100 transferts au premier passage, comme les autres historiques


def _api(env: Env, http: Http, path: str, step: str) -> Any:
    url = f"{env.cfg.market.multiversx_api_url}{path}"
    return net.polite(http, url, step, env.cfg.market.chain_pause_seconds)


def _egld(raw: Any) -> Decimal:
    return net.scaled(raw or 0, 18)


def egld_wallet(env: Env, http: Http, w: dict[str, Any]) -> dict[str, Decimal]:
    """EGLD disponible, délégué à un fournisseur de staking, en cours de retrait et
    récompenses à réclamer : tout compte, comme un ATOM mis en jeu."""
    total = Decimal(0)
    try:
        for a in w["addresses"]:
            total += _egld(_api(env, http, f"/accounts/{a}", "wallet.egld")["balance"])
            for d in _api(env, http, f"/accounts/{a}/delegation", "wallet.egld") or []:
                total += _egld(d.get("userActiveStake")) + _egld(d.get("claimableRewards"))
                total += _egld(d.get("userUnBondable"))
                total += sum(
                    (_egld(u.get("amount")) for u in d.get("userUndelegatedList") or []),
                    Decimal(0),
                )
    except (KeyError, TypeError, ValueError, ArithmeticError, AttributeError):
        raise Failure("invalid_file", "wallet.egld") from None
    return {"EGLD": total} if total else {}


# fonctions du contrat de délégation : les EGLD restent à moi (déjà dans le solde)
STAYS = {"delegate", "unDelegate", "withdraw", "unBond", "reDelegateRewards"}


@dataclass
class Tx:
    on: str = ""
    moved: Decimal = Decimal(0)
    fee: Decimal = Decimal(0)
    function: str = ""

    def move(self, txid: str) -> Move | None:
        net = (Decimal(0) if self.function in STAYS else self.moved) - self.fee
        if not (net or self.fee):
            return None
        stake = "stake" if self.function == "claimRewards" else ""
        return (self.on, txid, "EGLD", net, self.fee, stake)


def egld_moves(
    env: Env, http: Http, w: dict[str, Any], chained: set[str]
) -> tuple[list[Move], dict[str, str], list[str]]:
    """Transferts EGLD réussis de l'adresse, regroupés par transaction (ses résultats de
    contrat la rejoignent), frais payés sur ce qu'elle envoie. Les EGLD délégués restent à moi
    (le solde les compte) : une délégation, un retrait de délégation ou sa récupération ne
    bougent que les frais ; une récompense réclamée est une arrivée de staking. Tout la
    première fois (mémoire `<compte>@multiversx`), ensuite la page la plus récente."""
    label = f"{w['account']}@multiversx"
    full = label not in chained
    out: dict[str, Tx] = {}
    truncated = False
    try:
        for a in w["addresses"]:
            for page in range(PAGES if full else 1):
                params = urllib.parse.urlencode(
                    {"from": page * 100, "size": 100, "status": "success"}
                )
                rows = _api(env, http, f"/accounts/{a}/transfers?{params}", "history.egld")
                for r in rows:
                    if r.get("isRefund"):  # le gaz rendu : déjà déduit du frais de la transaction
                        continue
                    # un résultat de contrat (récompense versée) rejoint sa transaction
                    tx = out.setdefault(str(r.get("originalTxHash") or r["txHash"]), Tx())
                    value, sent = _egld(r.get("value")), r.get("sender") == a
                    tx.moved += (value if r.get("receiver") == a else 0) - (value if sent else 0)
                    if r.get("type") == "Transaction":
                        tx.function = str(r.get("function") or "")
                        tx.fee += _egld(r.get("fee")) if sent else 0
                    day = datetime.fromtimestamp(int(r["timestamp"]), UTC).date().isoformat()
                    tx.on = min(tx.on or day, day)
                if len(rows) < 100:
                    break
            else:
                truncated = full
    except (KeyError, TypeError, ValueError, ArithmeticError, AttributeError):
        raise Failure("invalid_file", "history.egld") from None
    moves = sorted(m for k, tx in out.items() if (m := tx.move(k)))
    if truncated:  # dit, et relu en entier au prochain passage
        return moves, {}, [f"history.{str(w['account']).split(':', 1)[1]}.multiversx:truncated"]
    first = {label: min((m[0] for m in moves), default=env.today.isoformat())}
    return moves, first if full else {}, []
