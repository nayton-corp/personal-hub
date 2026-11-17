"""Frais courants (TER) des fonds détenus (collecteur « market », market/fees.py) : une cascade par
ISIN, un lecteur par site (liste de fonds d'une plateforme, fiche du fonds, fiche de cotation par
symbole), un fichier `isin,ter_pct,origin,on_date` déposé que le domaine Finance lit. Pages
factices, à la forme des pages réelles (tableau ISIN · devise · TER ; libellé puis chiffre)."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from hub.collectors.http import Http
from hub.collectors.market import fees
from hub.domains.finance.patrimoine.infra import fee_file
from tests.collectors.conftest import FakeHub
from tests.collectors.test_http_collectors import Fake

LISTED = "CH0000000011"  # ISIN fictifs, forme valide
EUROPEAN = "IE0000000012"
AMERICAN = "US0000000013"
NOWHERE = "LU0000000014"
LIST_URL = "https://platform.example/funds/"
# une liste de plateforme : nom, indice, ISIN, devise, TER, fiche
LIST_PAGE = f"""<html><body><table>
<tr><th>Name</th><th>Details</th><th>ISIN</th><th>Currency</th><th>TER</th><th>Factsheet</th></tr>
<tr><td>Fund A</td><td>Index 20</td><td>{LISTED}</td><td>CHF</td><td>0.01%</td>
<td><a href="/a.pdf">Factsheet</a></td></tr>
<tr><td>Fund B</td><td>Index 100</td><td>CH0000000099</td><td>USD</td><td>0.30%</td>
<td><a href="/b.pdf">Factsheet</a></td></tr>
</table></body></html>"""
# une fiche finanzfluss : le libellé, une infobulle, puis le chiffre à la virgule
FUND_PAGE = """<html><body><div class="info"><span>TER</span><button>?</button>
<span class="tooltip">Tooltip anzeigen</span><b>0,22%</b></div>
<h3>Stammdaten</h3><dl><dt>Gesamtkosten (TER)</dt><dd>0,22%</dd><dt>Ertragsverwendung</dt>
<dd>Thesaurierend</dd></dl></body></html>"""
# une fiche de cotation : un tableau libellé · chiffre
QUOTE_PAGE = """<table><tr><td>Assets</td><td>1.00B</td></tr>
<tr><td>Expense Ratio</td><td>0.03%</td></tr><tr><td>PE Ratio</td><td>24.35</td></tr></table>"""


def sites(*, down: str | None = None) -> Fake:
    def route(method: str, url: str, data: bytes | None) -> tuple[int, bytes]:
        if down and down in url:
            return 503, b""
        if url == LIST_URL:
            return 200, LIST_PAGE.encode()
        if url == f"https://www.finanzfluss.de/informer/fonds/{EUROPEAN.lower()}/":
            return 200, FUND_PAGE.encode()
        if url == "https://stockanalysis.com/etf/test/":
            return 200, QUOTE_PAGE.encode()
        return 404, b""

    return Fake(route)


def held(*isins: str, **extra: object) -> list[dict[str, object]]:
    return [{"isin": i, "since": None, "stable": False, **extra} for i in isins]


def env_for(make_env: Any) -> Any:
    return make_env("market", market={"fee_lists": [LIST_URL], "quotes": {AMERICAN: "TEST"}})


def dropped(env: Any) -> list[fee_file.Fee]:
    out: list[fee_file.Fee] = []
    for p in sorted(env.inbox_root.glob("*fund-fees.csv")):
        data = p.read_bytes()
        assert fee_file.detect(p.name, data) == fee_file.SOURCE
        out += fee_file.parse(fee_file.SOURCE, data).fees
    return out


def test_each_fund_gets_its_ter_from_the_first_site_that_knows_it(
    make_env: Any, fake_hub: FakeHub
) -> None:
    fake_hub.funds = held(LISTED, EUROPEAN, AMERICAN, NOWHERE)
    env = env_for(make_env)
    site = sites()
    # le fonds qu'aucun site ne connaît est dit, sans bloquer le passage
    assert fees.run(env, Http(site)) == (1, ["fees:not_found=1"])
    got = {f.isin: (f.ter, f.origin, f.on_date) for f in dropped(env)}
    today = env.today.isoformat()
    assert got == {
        LISTED: (Decimal("0.0001"), "platform.example", today),
        EUROPEAN: (Decimal("0.0022"), "finanzfluss.de", today),
        AMERICAN: (Decimal("0.0003"), "stockanalysis.com", today),
    }  # NOWHERE : aucun site ne le connaît, il reste « frais inconnus »
    # la liste n'est lue qu'une fois pour tous les fonds ; seuls ISIN et symboles sont partis
    urls = [u for _m, u in site.calls]
    assert urls.count(LIST_URL) == 1
    assert all(u == LIST_URL or "informer" in u or "/etf/" in u for u in urls)
    # le jour même, plus rien n'est demandé
    assert fees.run(env, Http(sites())) == (0, [])


def test_a_ter_typed_by_hand_or_recent_is_not_looked_up(make_env: Any, fake_hub: FakeHub) -> None:
    env = env_for(make_env)
    recent = (env.today - timedelta(days=10)).isoformat()
    old = (env.today - timedelta(days=200)).isoformat()
    fake_hub.funds = (
        held(LISTED, ter_by_user=True)
        + held(EUROPEAN, ter_since=recent)
        + held(AMERICAN, ter_since=old)
    )
    assert fees.run(env, Http(sites())) == (1, [])
    assert [f.isin for f in dropped(env)] == [AMERICAN]
    # une actualisation forcée relit les TER récents, jamais une saisie
    env.forced = True
    assert fees.run(env, Http(sites())) == (1, [])
    assert sorted(f.isin for f in dropped(env)) == sorted(
        [AMERICAN, AMERICAN, EUROPEAN]
    )  # 2 fichiers


def test_a_site_down_does_not_stop_the_others(make_env: Any, fake_hub: FakeHub) -> None:
    fake_hub.funds = held(LISTED, EUROPEAN)
    env = env_for(make_env)
    # la plateforme en panne : le fonds européen est lu quand même ; le fonds de la liste est
    # cherché ailleurs, en vain, et le passage le dit
    # le manque nomme le site et sa réponse
    assert fees.run(env, Http(sites(down="platform.example"))) == (1, ["fees.list:http_503"])
    assert [f.isin for f in dropped(env)] == [EUROPEAN]
    assert env.memory.get(fees.DAY_KEY) is None  # redemandé au passage suivant
    assert fees.run(env, Http(sites())) == (1, [])


def test_the_ter_follows_its_label_without_another_number_between() -> None:
    assert fees.in_list(fees.page_text(LIST_PAGE.encode()), LISTED) == Decimal("0.01")
    assert fees.in_list("CH0000000011 | CHF | 1'000 | 0.20%", LISTED) is None  # autre chiffre
    assert fees.in_list("CH0000000011 CHF 9%", LISTED) is None  # au-delà de 5 % : douteux
    page = fees.page_text(b"<td>Expense Ratio</td><script>var x='1%'</script><td>0.07%</td>")
    assert fees.STOCKANALYSIS_LABEL.search(page) is not None


def test_due() -> None:
    today = date(2026, 11, 16)
    assert fees.due({"isin": LISTED}, today, 90)
    assert fees.due({"isin": LISTED, "ter_since": "2026-08-18"}, today, 90)
    assert not fees.due({"isin": LISTED, "ter_since": "2026-08-19"}, today, 90)
    assert not fees.due({"isin": LISTED, "ter_by_user": True}, today, 0)
    assert fees.due({"isin": LISTED, "ter_since": "illisible"}, today, 90)
