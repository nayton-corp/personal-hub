"""Opérations d'une plateforme crypto dans un fichier `hub.market.v1` : lecture et contrôle des
jambes (actif, quantité signée, rôle), sans rien écrire."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from hub.domains.finance.patrimoine.model import instruments
from hub.domains.finance.patrimoine.model.instruments import AssetError, DocumentError

ROLES = frozenset({"deposit", "withdrawal", "trade", "income", "fee"})
KINDS = {  # nature de l'opération → libellé d'une récompense
    "deposit": "",
    "withdrawal": "",
    "fiat_deposit": "",
    "fiat_withdrawal": "",
    "card_buy": "",
    "card_sell": "",
    "trade": "",
    "convert": "",
    "dust": "",
    "reward": "Récompense Earn",
    "distribution": "Distribution",
}
STABLE = frozenset({"USDT", "USDC", "BUSD", "FDUSD", "TUSD", "USDP", "DAI"})
_ACCOUNT = re.compile(r"^crypto:[a-z0-9][a-z0-9-]{0,40}$")
_ID = re.compile(r"^[A-Za-z0-9:._-]{1,160}$")


class ExchangeError(DocumentError):
    pass


@dataclass(frozen=True)
class Leg:
    symbol: str
    quantity: Decimal
    role: str
    value: Decimal | None = None  # contre-valeur donnée par la plateforme
    value_currency: str = ""

    @property
    def fiat(self) -> bool:
        return instruments.known_currency(self.symbol)


@dataclass(frozen=True)
class Operation:
    account: str
    id: str
    kind: str
    on_date: str
    legs: tuple[Leg, ...]
    txid: str = ""
    address: str = ""
    network: str = ""


def parse(items: list[Any], number: Any, iso: Any) -> list[Operation]:
    """Lignes `operations` ; `number` et `iso` : les lecteurs du fichier de cours."""
    out = []
    for x in items:
        if not isinstance(x, dict):
            continue
        account, op_id, kind = (str(x.get(k) or "") for k in ("account", "id", "kind"))
        if not _ACCOUNT.match(account):
            raise ExchangeError("plateforme illisible")
        if not _ID.match(op_id) or kind not in KINDS:
            raise ExchangeError("opération illisible")
        legs = []
        for leg in x.get("legs") or []:
            if not isinstance(leg, dict) or leg.get("role") not in ROLES:
                raise ExchangeError("jambe d'opération illisible")
            symbol = str(leg.get("instrument") or "").upper()
            try:
                instruments.instrument_key(symbol, "crypto")
            except AssetError:
                raise ExchangeError("instrument illisible") from None
            value, ccy = leg.get("value"), str(leg.get("value_currency") or "").upper()
            known = value is not None and instruments.known_currency(ccy)
            legs.append(
                Leg(
                    symbol,
                    number(leg.get("quantity")),
                    str(leg["role"]),
                    abs(number(value)) if known else None,
                    ccy if known else "",
                )
            )
        if not legs:
            raise ExchangeError("opération sans jambe")
        extra = {k: str(x.get(k) or "")[:128] for k in ("txid", "address", "network")}
        out.append(Operation(account, op_id, kind, iso(x.get("on_date")), tuple(legs), **extra))
    out.sort(key=lambda o: (o.on_date, o.id))
    return out
