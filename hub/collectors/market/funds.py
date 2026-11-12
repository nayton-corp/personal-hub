"""Compositions des fonds détenus (collecteur « market ») : le hub donne la liste de ses fonds
(`GET /collectors/<connexion>/needs`, l'ISIN et la date de la dernière composition connue) ; pour
chaque fonds dont la composition a au moins `funds_refresh_days` jours, le collecteur dépose la
liste des lignes publiée par l'émetteur sous le nom `<ISIN>.csv`. Le domaine Finance la lit comme
un fichier déposé à la main (patrimoine/infra/composition.py) et garde chaque date.

Un lecteur par émetteur, pas par fonds : tous les fonds d'un émetteur publient le même fichier.

- iShares : la recherche du site par ISIN donne l'identifiant du fonds, puis
  `latest-holdings.csv` (ligne, secteur, pays, devise). La recherche ne rend pas l'ISIN : un seul
  résultat est exigé, deux seraient une devinette.

Un fonds qu'aucun lecteur ne connaît (HSBC, Vanguard, fonds UBS non cotés…) peut lire la
composition d'un ETF qui suit le même indice : réglage `funds` (ISIN détenu → ISIN de l'ETF).
Sinon il reste sans composition, et le hub le signale. Un passage par jour au plus ; seuls des
ISIN quittent la machine.
"""

from __future__ import annotations

import urllib.parse
from collections.abc import Callable
from datetime import date

from hub.collectors.base import Failure
from hub.collectors.client import HubUnavailable
from hub.collectors.http import Http
from hub.collectors.runtime import Env

DAY_KEY = "funds_day"  # dernier jour où toutes les compositions dues ont été demandées
# sites iShares interrogés : (site de la recherche, langue, chemin des pages publiques)
ISHARES_SITES = (("ishares-uk", "en-gb", "uk"),)
HEADER_WORDS = (b"Weight (%)", b"Name")  # une liste de lignes que le hub sait lire

Reader = Callable[[Env, Http, str], bytes | None]


def ishares(env: Env, http: Http, isin: str) -> bytes | None:
    """La liste des lignes d'un fonds iShares, ou None si iShares ne le connaît pas."""
    base = env.cfg.market.ishares_url
    for site, locale, path in ISHARES_SITES:
        query = urllib.parse.urlencode(
            {
                "site": site,
                "locale": locale,
                "rows": 5,
                "start": 0,
                "userType": "individual",
                "query": isin,
            }
        )
        url = f"{base}/varnish-api/core-search/search/products?{query}"
        doc = http.json(url, "funds.ishares_search")
        results = doc.get("results") if isinstance(doc, dict) else None
        if not isinstance(results, list) or len(results) != 1 or not isinstance(results[0], dict):
            continue
        fund_id = str(results[0].get("portfolioId") or "")
        if not fund_id.isdigit():
            continue
        # le segment après l'identifiant est libre (le nom du fonds sur le site)
        csv_url = f"{base}/{path}/individual/en/products/{fund_id}/fonds/latest-holdings.csv"
        return http.call(csv_url, "funds.ishares_holdings")
    return None


READERS: tuple[Reader, ...] = (ishares,)


def readable(data: bytes) -> bool:
    return all(w in data[:4000] for w in HEADER_WORDS)


def due(fund: dict[str, object], today: date, days: int) -> bool:
    """Une composition à chercher : jamais lue, ou lue il y a au moins `days` jours. Un fonds
    entièrement dans une seule case (or, immobilier suisse) ne change pas : on ne le cherche
    pas."""
    if fund.get("stable") is True:
        return False
    since = fund.get("since")
    if not isinstance(since, str) or not since:
        return True
    try:
        return (today - date.fromisoformat(since)).days >= days
    except ValueError:
        return True


def labelled(isin: str, source: str, data: bytes) -> bytes:
    """La liste, précédée du fonds pour lequel elle est lue : deux fonds qui lisent le même ETF
    déposent deux fichiers distincts (la boîte d'entrée écarte un contenu déjà vu)."""
    return f"Composition pour,{isin},lue sur,{source}\n".encode() + data


def run(env: Env, http: Http) -> tuple[int, list[str]]:
    """(fichiers déposés, manques du passage). Sans hub (tests, essai à la main), rien."""
    if env.client is None or env.memory.get(DAY_KEY) == env.today.isoformat():
        return 0, []
    try:
        funds = env.client.needs(env.name).get("funds", [])
    except HubUnavailable:
        return 0, ["funds:hub_unavailable"]
    m = env.cfg.market
    dropped, failed = 0, ""
    for fund in funds:
        isin = str(fund.get("isin") or "") if isinstance(fund, dict) else ""
        if not isin or not due(fund, env.today, m.funds_refresh_days):
            continue
        source = m.funds.get(isin, isin)
        try:
            data = next((d for read in READERS if (d := read(env, http, source)) is not None), None)
            if data is not None:
                dropped += env.inbox.drop(
                    f"{isin}.csv", labelled(isin, source, data), readable, step="funds.file"
                )
        except Failure as f:
            failed = failed or f.outcome  # les autres fonds passent ; on réessaie demain
    if not failed:
        env.memory.put(DAY_KEY, env.today.isoformat())
    return dropped, [f"funds:{failed}"] if failed else []
