"""Mes placements depuis l'achat : un gain par classe. Cryptos au prix de revient, titres par la
performance « Max » plus dividendes moins frais, 3e pilier en valeur moins versements nets."""

from __future__ import annotations

from hub.domains.finance.domain import FinanceDomain
from hub.domains.finance.patrimoine.app import placements
from hub.platform.db import begin_immediate
from tests.finance.conftest import ready_account
from tests.finance.test_crypto_cost import setup
from tests.finance.test_performance import chf, entry, price, ref, trade

ON = "2026-10-27"


def test_one_gain_per_class(finance: FinanceDomain) -> None:
    ready_account(finance, 100_000)  # un compte bancaire : pas de prix d'achat, hors placements
    setup(finance)  # cryptos : −60 CHF depuis l'achat
    titres = ref(finance, "test:titres", "securities")
    pilier = ref(finance, "test:3a", "pension")
    with begin_immediate(finance.engine()) as conn:
        price(conn, "2026-10-02", "100")
        trade(conn, titres, "2026-10-02", "10", 100_000)  # 10 parts à 100
        entry(conn, titres, "2026-10-10", 2_000, "IBKR/INCOME")  # dividende
        entry(conn, titres, "2026-10-11", -500, "IBKR/FEE")
        price(conn, "2026-10-20", "110")
        entry(conn, pilier, "2026-10-01", 500_000)  # versement de 5 000 sur le 3a
        entry(conn, pilier, "2026-10-26", 20_000, "VIAC/INCOME")  # rendement
    with finance.engine().connect() as conn:
        r = placements.summary(conn, ON)
    by = {c["kind"]: c for c in r["classes"]}
    assert set(by) == {"crypto", "securities", "pension"}
    assert chf(by["crypto"]["result"]) == -6_000
    sec = by["securities"]
    assert (chf(sec["value"]), chf(sec["unrealized"])) == (110_000, 10_000)
    assert (chf(sec["income"]), chf(sec["fees"]), chf(sec["result"])) == (2_000, -500, 11_500)
    pen = by["pension"]
    assert (chf(pen["value"]), chf(pen["deposits"]), chf(pen["result"])) == (
        520_000,
        500_000,
        20_000,
    )
    assert chf(r["result"]) == -6_000 + 11_500 + 20_000
