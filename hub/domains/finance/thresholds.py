"""Les seuils de la finance (audit m2) : dans les réglages `[finance]`, exprimés en devise de
base ou en jours, plus en constantes d'un module. Sans réglage, 1 unité de la devise de base
(100 centimes, 1 yen) de tolérance au rapprochement, 45 jours sans donnée pour un compte à
rafraîchir, 14 jours (3 pour une crypto) pour un cours ancien, 7 pour un change ancien.

```toml
[finance]
tolerance_minor = 100          # rupture du rapprochement ignorée en dessous (mineures)
stale_account_days = 45        # compte sans donnée depuis plus longtemps : à rafraîchir
stale_price_days = 14          # cours plus vieux : ancien
stale_crypto_price_days = 3
stale_fx_days = 7              # change plus vieux : ancien (audit M6)
quantity_epsilon = "1e-9"      # reste d'arrondi d'une quantité tenu pour zéro
event_floor_minor = 150000     # événement de la courbe : flux d'au moins 1 500 (mineures)…
event_share_pct = 4            # … ou 4 % de la valeur de la veille, le plus grand des deux
event_income_floor_minor = 1000  # revenu (dividende, coupon) montré à partir de 10
```
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from hub.kernel.money import base_currency, exponent
from hub.platform.settings import Settings, get_settings


@dataclass(frozen=True)
class Thresholds:
    tolerance_minor: int
    stale_account_days: int = 45
    stale_price_days: int = 14
    stale_crypto_price_days: int = 3
    stale_fx_days: int = 7
    quantity_epsilon: Decimal = Decimal("1e-9")
    event_floor_minor: int = 150_000
    event_share_pct: int = 4
    event_income_floor_minor: int = 1_000

    def price_stale_days(self, kind: str) -> int:
        return self.stale_crypto_price_days if kind == "crypto" else self.stale_price_days

    @classmethod
    def from_section(cls, section: Mapping[str, Any], currency: str | None = None) -> Thresholds:
        unit = 10 ** exponent(currency or base_currency())  # 1 unité de la devise de base
        return cls(
            tolerance_minor=int(section.get("tolerance_minor", unit)),
            stale_account_days=int(section.get("stale_account_days", 45)),
            stale_price_days=int(section.get("stale_price_days", 14)),
            stale_crypto_price_days=int(section.get("stale_crypto_price_days", 3)),
            stale_fx_days=int(section.get("stale_fx_days", 7)),
            quantity_epsilon=Decimal(str(section.get("quantity_epsilon", "1e-9"))),
            event_floor_minor=int(section.get("event_floor_minor", 1500 * unit)),
            event_share_pct=int(section.get("event_share_pct", 4)),
            event_income_floor_minor=int(section.get("event_income_floor_minor", 10 * unit)),
        )


def of(settings: Settings) -> Thresholds:
    return Thresholds.from_section(settings.domain("finance"))


def current() -> Thresholds:
    """Pour le code qui n'a pas les réglages sous la main ; une lecture par calcul."""
    return of(get_settings())
