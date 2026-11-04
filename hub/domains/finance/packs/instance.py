"""Le pack de cette instance : celui du pays du profil (`core.db`), ou de `HUB_COUNTRY` tant
qu'aucun profil n'est enregistré. Les lectures d'une route le demandent une fois par appel."""

from __future__ import annotations

from hub.core import profile
from hub.domains.finance.packs import CountryPack, pack
from hub.platform.settings import Settings, get_settings


def of(settings: Settings) -> CountryPack:
    return pack(profile.load(settings).country)


def current() -> CountryPack:
    """Pour le code qui n'a ni domaine ni réglages sous la main (lectures du registre)."""
    return of(get_settings())
