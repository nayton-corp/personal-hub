"""Règle du hub : un connecteur crypto amène ses écritures au Journal, pas seulement des soldes.
Une plateforme ou une crypto de portefeuille ajoutée sans historique fait échouer ce test."""

from __future__ import annotations

from hub.collectors import runtime
from hub.collectors.market import flow as market
from hub.core.connectors import CATALOG


def test_every_crypto_connector_reads_its_history() -> None:
    flows = runtime.flows()
    crypto = [c.name for c in CATALOG if "crypto" in c.accounts]
    assert crypto  # le catalogue en a
    for name in crypto:
        if name == "market":
            continue  # portefeuilles : ci-dessous
        assert getattr(flows[name], "history", None) is not None, name


def test_every_wallet_asset_reads_its_history() -> None:
    # BTC : xpub et adresses relues sur mempool.space (`btc_moves`)
    assert set(market.WALLETS) == {"BTC", *market.HISTORIES}
