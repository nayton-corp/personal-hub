"""Compositions des fonds détenus (collecteur « market ») : le hub dit quels fonds il détient, le
collecteur dépose la liste des lignes publiée par iShares (format réel du 10/11/2026), une fois
par jour, pour un fonds connu d'iShares ou qui lit l'ETF du même indice ; le domaine Finance la lit
comme un fichier déposé à la main."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from typing import Any
from urllib.parse import parse_qs, urlsplit

from hub.collectors.http import Http
from hub.collectors.market import flow as market
from hub.collectors.market import funds
from hub.domains.finance.packs import ch
from hub.domains.finance.patrimoine.infra import composition
from tests.collectors.conftest import FakeHub
from tests.collectors.test_http_collectors import Fake, market_api

CSPX = "IE00B5BMR087"  # iShares Core S&P 500
ISHARES_EM = "IE00B0M63177"  # iShares MSCI Emerging Markets
HSBC_EM = "IE000KCS7J59"  # suit MSCI Emerging Markets, sans fichier lisible
UBS_EM = "CH1600525138"  # même indice, fonds non coté
VOO = "US9229083632"  # inconnu d'iShares, sans ETF répliqué réglé
CSSMI = "CH0008899764"  # iShares SMI (CH) : connu du seul site suisse
UBS_SMI = "CH0033782431"  # suit le SMI
IDS = {CSPX: "253743", ISHARES_EM: "251857"}
CH_IDS = {CSSMI: "261154"}
# en-tête et lignes recopiés du fichier iShares réel (latest-holdings.csv), poids arrondis
HOLDINGS = (
    'Fund Holdings as of,"10/Nov/2026"\n'
    "\n"
    "Ticker,Name,Sector,Asset Class,Market Value,Weight (%),Notional Value,Shares,Price,"
    "Location,Exchange,Market Currency\n"
    '"AAPL","APPLE","Information Technology","Equity","12,294,063,852.72","60.00",'
    '"12,294,063,852.72","35,276,072.00","348.51","United States","NASDAQ","USD"\n'
    '"NESN","NESTLE","Consumer Staples","Equity","1,000.00","30.00","1,000.00","10.00",'
    '"100.00","Switzerland","SIX Swiss Exchange","CHF"\n'
    '"ESZ6","S&P500 EMINI DEC 26","Cash and/or Derivatives","Futures","0.00","10.00",'
    '"1.00","1.00","1.00","-","-","USD"\n'
)
# le site suisse : BOM, ligne 2 faite d'une espace insécable, milliers « ’ » (SMIM, 12/11/2026)
SWISS = (
    '\ufeffFund Holdings as of,"10/Nov/2026"\n'
    "\u00a0\n"
    "Ticker,Name,Sector,Asset Class,Market Value,Weight (%),Notional Value,Shares,Price,"
    "Location,Exchange,Market Currency\n"
    '"DSFIR","DSM FIRMENICH AG","Materials","Equity","89’755’623.25","90.00","89’755’623.25",'
    '"922’937.00","97.25","Netherlands","SIX Swiss Exchange","CHF"\n'
    '"S1Z6","SWISS MID CAP DEC 26","Cash and/or Derivatives","Futures","0.00","10.00",'
    '"1.00","1.00","1.00","-","Eurex Deutschland","CHF"\n'
)


def ishares_site(*, down: bool = False) -> Fake:
    def route(method: str, url: str, data: bytes | None) -> tuple[int, bytes]:
        if down:
            return 503, b""
        parts = urlsplit(url)
        if parts.path == "/varnish-api/core-search/search/products":
            q = parse_qs(parts.query)
            ids = {("ishares-uk", "en-gb"): IDS, ("ishares-ch", "en-ch"): CH_IDS}[
                (q["site"][0], q["locale"][0])
            ]
            found = [{"portfolioId": ids[q["query"][0]]}] if q["query"][0] in ids else []
            return 200, json.dumps({"results": found, "totalResults": len(found)}).encode()
        if parts.path.startswith("/uk/") and parts.path.endswith("/latest-holdings.csv"):
            assert parts.path.split("/")[5] in IDS.values()
            return 200, HOLDINGS.encode()
        if parts.path.startswith("/ch/") and parts.path.endswith(".ajax"):
            assert parts.path.split("/")[5] in CH_IDS.values()
            assert parse_qs(parts.query)["fileType"] == ["csv"]
            return 200, SWISS.encode()
        return 404, b""

    return Fake(route)


def dropped(env: Any) -> dict[str, bytes]:
    """{ISIN : contenu} des fichiers de composition déposés."""
    out = {}
    for p in sorted(env.inbox_root.glob("*.csv")):
        isin = composition.isin_from_name(p.name)
        assert isin is not None
        out[isin] = p.read_bytes()
    return out


def held(*isins: str, since: str | None = None, stable: bool = False) -> list[dict[str, object]]:
    return [{"isin": i, "since": since, "stable": stable} for i in isins]


def test_an_ishares_fund_gets_the_issuer_list_once_a_day(make_env: Any, fake_hub: FakeHub) -> None:
    fake_hub.funds = held(CSPX, VOO)
    env = make_env("market")
    site = ishares_site()
    assert funds.run(env, Http(site)) == (1, [])
    files = dropped(env)
    assert list(files) == [CSPX]  # VOO : ni iShares, ni ETF répliqué ; il reste sans
    name = next(env.inbox_root.glob("*.csv")).name
    source = composition.detect(name, files[CSPX])
    assert source == f"lookthrough:{CSPX}"
    (comp,) = composition.parse(source, files[CSPX], ch.PACK).compositions
    assert comp.on_date == "2026-11-10"
    by = {(w.dimension, w.bucket): w.weight for w in comp.weights}
    assert by[("sector", "Technologie")] == Decimal("0.6")
    assert by[("sector", "Consommation de base")] == Decimal("0.3")
    assert by[("sector", "Liquidités et dérivés")] == Decimal("0.1")  # futures : pas un secteur
    assert by[("region", composition.NORTH_AMERICA)] == Decimal("0.6")
    assert by[("region", ch.PACK.regions.home)] == Decimal("0.3")
    assert by[("region", composition.UNKNOWN)] == Decimal("0.1")  # « - » : sans pays
    # seuls des ISIN sont partis ; le jour même, le hub n'est plus interrogé
    assert all("query=" in u or "latest-holdings" in u for _m, u in site.calls)
    assert funds.run(env, Http(ishares_site())) == (0, [])
    assert fake_hub.needs_asked == 1


def test_a_forced_refresh_reads_every_fund_again_the_same_day(
    make_env: Any, fake_hub: FakeHub
) -> None:
    """« Actualiser » les compositions depuis l'app : chaque fonds est relu, même frais, même
    déjà lu ce jour-là ; un fonds stable (or, immobilier) reste sans."""
    env = make_env("market")
    fake_hub.funds = held(CSPX, since=env.today.isoformat()) + held(ISHARES_EM, stable=True)
    env.memory.put(funds.DAY_KEY, env.today.isoformat())
    assert funds.run(env, Http(ishares_site())) == (0, [])
    env.forced = True
    assert funds.run(env, Http(ishares_site())) == (1, [])
    assert list(dropped(env)) == [CSPX]


def test_a_fund_reads_the_etf_that_follows_the_same_index(make_env: Any, fake_hub: FakeHub) -> None:
    fake_hub.funds = held(HSBC_EM, UBS_EM)
    env = make_env("market", market={"funds": {HSBC_EM: ISHARES_EM, UBS_EM: ISHARES_EM}})
    site = ishares_site()
    assert funds.run(env, Http(site)) == (2, [])
    files = dropped(env)
    # deux fichiers, chacun au nom du fonds détenu, même s'ils lisent le même ETF
    assert sorted(files) == [UBS_EM, HSBC_EM]
    assert files[HSBC_EM] != files[UBS_EM]
    assert files[HSBC_EM].startswith(f"Composition pour,{HSBC_EM},lue sur,{ISHARES_EM}".encode())
    (comp,) = composition.parse(f"lookthrough:{UBS_EM}", files[UBS_EM]).compositions
    assert (comp.isin, comp.on_date) == (UBS_EM, "2026-11-10")
    assert {parse_qs(urlsplit(u).query).get("query", [""])[0] for _m, u in site.calls} >= {
        ISHARES_EM
    }


def test_a_swiss_etf_is_read_on_the_swiss_site(make_env: Any, fake_hub: FakeHub) -> None:
    fake_hub.funds = held(UBS_SMI)
    env = make_env("market", market={"funds": {UBS_SMI: CSSMI}})
    site = ishares_site()
    assert funds.run(env, Http(site)) == (1, [])
    data = dropped(env)[UBS_SMI]
    assert b"\xef\xbb\xbf" not in data
    (comp,) = composition.parse(f"lookthrough:{UBS_SMI}", data, ch.PACK).compositions
    assert (comp.isin, comp.on_date) == (UBS_SMI, "2026-11-10")
    by = {(w.dimension, w.bucket): w.weight for w in comp.weights}
    assert by[("sector", "Matériaux")] == Decimal("0.9")
    assert by[("region", composition.UNKNOWN)] == Decimal("0.1")
    sites = [parse_qs(urlsplit(u).query).get("site") for _m, u in site.calls]
    assert sites[:2] == [["ishares-uk"], ["ishares-ch"]]  # le site britannique d'abord


def test_a_recent_or_stable_composition_is_not_fetched_again() -> None:
    today = date(2026, 10, 27)
    assert funds.due({"isin": CSPX, "since": None}, today, 7)
    assert funds.due({"isin": CSPX, "since": "2026-10-20"}, today, 7)
    assert not funds.due({"isin": CSPX, "since": "2026-10-21"}, today, 7)
    assert not funds.due({"isin": CSPX, "since": None, "stable": True}, today, 7)  # or, immobilier
    assert funds.due({"isin": CSPX, "since": "illisible"}, today, 7)


def test_a_site_down_is_a_gap_retried_at_the_next_pass(make_env: Any, fake_hub: FakeHub) -> None:
    fake_hub.funds = held(CSPX)
    env = make_env("market")
    assert funds.run(env, Http(ishares_site(down=True))) == (0, ["funds:site_unavailable"])
    assert env.memory.get(funds.DAY_KEY) is None
    assert funds.run(env, Http(ishares_site())) == (1, [])


def test_the_market_run_drops_the_compositions_with_the_rest(
    make_env: Any, fake_hub: FakeHub
) -> None:
    fake_hub.funds = held(CSPX)
    env = make_env("market", market={"crypto": {}, "erc20_tokens": {}, "staking_tokens": {}})
    rest, site = market_api(), ishares_site()
    both = Fake(lambda m, u, d: site.route(m, u, d) if "ishares" in u else rest.route(m, u, d))
    result = market.run(env, "run", Http(both))
    assert (result.outcome, result.files, result.detail) == ("ok", 2, None)
    assert list(dropped(env)) == [CSPX]
    later = make_env("market", market={"crypto": {}, "erc20_tokens": {}, "staking_tokens": {}})
    fake_hub.funds = held(CSPX)
    down = Fake(lambda m, u, d: (503, b"") if "ishares" in u else rest.route(m, u, d))
    assert market.run(later, "run", Http(down)).detail == "partial funds:site_unavailable"
