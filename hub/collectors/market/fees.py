"""Frais courants (TER) des fonds détenus (collecteur « market ») : le hub donne la liste de ses
fonds (`GET /collectors/<connexion>/needs`, avec la date du dernier TER connu et s'il a été saisi
à la main) ; pour chaque fonds sans TER, ou dont le TER a au moins `fees_refresh_days` jours, le
collecteur cherche le TER publié et dépose un petit fichier `isin,ter_pct,origin,on_date` que le
domaine Finance lit (patrimoine/infra/fee_file.py). Un TER saisi à la main n'est jamais cherché.

Une cascade par ISIN, chaque lecteur générique (un par site, jamais un par fonds) :

1. les listes de fonds publiées par une plateforme (`fee_lists`, par défaut celles de VIAC :
   ISIN, devise et TER de chaque fonds proposé, y compris les classes non cotées) ;
2. la fiche du fonds sur finanzfluss (ETF puis fonds : ETF et fonds européens par ISIN) ;
3. la fiche de cotation sur stockanalysis, pour un fonds dont le symbole est réglé dans `quotes`
   (ETF américains, cotations suisses, londoniennes…).

Un fonds qu'aucun lecteur ne connaît reste « frais inconnus » ; le TER se saisit alors à la main.
Les pages se lisent en texte (balises retirées) : un libellé, puis le premier pourcentage qui le
suit, sans chiffre entre les deux. Un passage par jour au plus, sauf actualisation forcée depuis
l'app ; seuls des ISIN et des symboles quittent la machine.
"""

from __future__ import annotations

import html
import re
from collections.abc import Callable
from datetime import date
from decimal import Decimal, InvalidOperation

from hub.collectors.base import Failure
from hub.collectors.client import HubUnavailable
from hub.collectors.http import Http
from hub.collectors.market import funds
from hub.collectors.runtime import Env
from hub.platform.logging import get_logger

log = get_logger("hub.collector.fees")
DAY_KEY = "fees_day"
HEADER = "isin,ter_pct,origin,on_date"
MAX_TER_PCT = Decimal(5)
# des sites qui refusent un client sans navigateur : on se présente, sans se déguiser
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; personal-hub/1.0)",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en,de;q=0.8,fr;q=0.6",
}
_TAGS = re.compile(r"<(script|style)\b.*?</\1>|<[^>]+>", re.S | re.I)
_SPACES = re.compile(r"\s+")
_PCT = r"(\d{1,2}(?:[.,]\d{1,4})?)\s*%"
# libellé du TER sur une fiche, puis le chiffre (sans autre chiffre entre les deux)
FINANZFLUSS_LABEL = re.compile(r"Gesamtkosten \(TER\)[^0-9%]{0,80}?" + _PCT)
STOCKANALYSIS_LABEL = re.compile(r"Expense Ratio[^0-9%]{0,80}?" + _PCT)
# suffixe Yahoo → place de stockanalysis (`/quote/<place>/<symbole>/`) ; sans suffixe : un ETF
# américain (`/etf/<symbole>/`)
PLACES = {"SW": "swx", "L": "lon", "DE": "etr", "AS": "ams", "PA": "epa", "MI": "bit"}

Found = tuple[Decimal, str]  # (TER en % par an, site)
Pages = dict[str, str]  # pages de listes déjà lues pendant le passage (adresse → texte)
Reader = Callable[[Env, Http, str, Pages], Found | None]


def page_text(raw: bytes) -> str:
    """Le texte d'une page HTML : balises, scripts et styles retirés, espaces réduits."""
    doc = raw.decode("utf-8", errors="replace")
    return _SPACES.sub(" ", html.unescape(_TAGS.sub(" ", doc)))


def pct(value: str) -> Decimal | None:
    try:
        out = Decimal(value.replace(",", "."))
    except InvalidOperation:
        return None
    return out if 0 <= out <= MAX_TER_PCT else None


def site_of(url: str) -> str:
    host = url.split("://", 1)[-1].split("/", 1)[0]
    return host.removeprefix("www.")


def get(http: Http, url: str, step: str) -> bytes | None:
    """La page, ou None si le site ne connaît pas le fonds (404, 410)."""
    try:
        return http.call(url, step, headers=HEADERS)
    except Failure as f:
        if f.detail.endswith((":http_404", ":http_410")):
            return None
        raise


def in_list(text: str, isin: str) -> Decimal | None:
    """Le TER d'un fonds dans une liste de plateforme : l'ISIN, éventuellement la devise, puis
    le premier pourcentage, sans autre chiffre entre les deux."""
    m = re.search(re.escape(isin) + r"\b[^0-9%]{0,60}?" + _PCT, text)
    return pct(m.group(1)) if m else None


def platform_lists(env: Env, http: Http, isin: str, pages: Pages) -> Found | None:
    """Les listes sont lues une fois par passage, pour tous les fonds."""
    for url in env.cfg.market.fee_lists:
        if url not in pages:
            pages[url] = ""  # en panne : pas relue pour le fonds suivant
            raw = get(http, url, "fees.list")
            pages[url] = page_text(raw) if raw is not None else ""
        ter = in_list(pages[url], isin)
        if ter is not None:
            return ter, site_of(url)
    return None


def finanzfluss(env: Env, http: Http, isin: str, _pages: Pages) -> Found | None:
    base = env.cfg.market.finanzfluss_url
    for kind in ("etf", "fonds"):
        raw = get(http, f"{base}/informer/{kind}/{isin.lower()}/", "fees.finanzfluss")
        if raw is None:
            continue
        m = FINANZFLUSS_LABEL.search(page_text(raw))
        ter = pct(m.group(1)) if m else None
        if ter is not None:
            return ter, site_of(base)
    return None


def stockanalysis(env: Env, http: Http, isin: str, _pages: Pages) -> Found | None:
    m = env.cfg.market
    ticker = m.quotes.get(isin)
    if not ticker:
        return None
    symbol, _, suffix = ticker.partition(".")
    if not suffix:
        path = f"/etf/{symbol.lower()}/"
    elif suffix.upper() in PLACES:
        path = f"/quote/{PLACES[suffix.upper()]}/{symbol.upper()}/"
    else:
        return None
    raw = get(http, m.stockanalysis_url + path, "fees.stockanalysis")
    found = STOCKANALYSIS_LABEL.search(page_text(raw)) if raw is not None else None
    ter = pct(found.group(1)) if found else None
    return (ter, site_of(m.stockanalysis_url)) if ter is not None else None


READERS: tuple[Reader, ...] = (platform_lists, finanzfluss, stockanalysis)


def due(fund: dict[str, object], today: date, days: int) -> bool:
    """Un TER à chercher : jamais connu, ou connu depuis au moins `days` jours ; jamais celui
    saisi à la main."""
    if fund.get("ter_by_user") is True:
        return False
    since = fund.get("ter_since")
    if not isinstance(since, str) or not since:
        return True
    try:
        return (today - date.fromisoformat(since)).days >= days
    except ValueError:
        return True


def readable(data: bytes) -> bool:
    return data.startswith(HEADER.encode() + b"\n")


def lookup(env: Env, http: Http, isin: str, pages: Pages) -> Found | None:
    """Le premier lecteur qui connaît le fonds. Un site en panne n'arrête pas la cascade : le
    suivant est essayé ; l'échec ne remonte que si personne n'a répondu."""
    failure: Failure | None = None
    for read in READERS:
        try:
            found = read(env, http, isin, pages)
        except Failure as f:
            failure = failure or f
            continue
        if found is not None:
            return found
    if failure is not None:
        raise failure
    return None


def gap(f: Failure) -> str:
    """`fees.<site>:<raison>` : le site et la réponse (`fees.list:http_403`), pour l'écran des
    sources."""
    step, _, why = f.detail.partition(":")
    return f"{step or 'fees'}:{why or f.outcome}"


def run(env: Env, http: Http) -> tuple[int, list[str]]:
    """(fichiers déposés, manques du passage). Sans hub (tests, essai à la main), rien.

    Un manque par site en échec (`fees.list:http_403`), et `fees:not_found=<n>` pour les fonds
    qu'aucun site ne publie : l'écran des sources dit pourquoi un TER manque."""
    if env.client is None or (not env.forced and env.memory.get(DAY_KEY) == env.today.isoformat()):
        return 0, []
    try:
        funds = env.client.needs(env.name).get("funds", [])
    except HubUnavailable:
        return 0, ["fees:hub_unavailable"]
    days = 0 if env.forced else env.cfg.market.fees_refresh_days
    pages: Pages = {}  # chaque passage relit les listes
    rows: list[str] = []
    failed: list[str] = []
    missing = 0
    for fund in funds:
        isin = str(fund.get("isin") or "") if isinstance(fund, dict) else ""
        if not isin or not due(fund, env.today, days):
            continue
        try:
            found = lookup(env, http, isin, pages)
        except Failure as f:
            failed.append(gap(f))  # les autres fonds passent ; on réessaie demain
            continue
        if found is None:
            missing += 1
            continue
        ter, origin = found
        rows.append(f"{isin},{format(ter.normalize(), 'f')},{origin},{env.today.isoformat()}")
    log.info(
        "collector.fees", asked=len(funds), found=len(rows), missing=missing, failed=len(failed)
    )
    dropped = 0
    if rows:
        data = "\n".join([HEADER, *rows]).encode() + b"\n"
        dropped = int(env.inbox.drop("fund-fees.csv", data, readable, step="fees.file"))
    if not failed:
        env.memory.put(DAY_KEY, env.today.isoformat())
    gaps = sorted(set(failed)) + ([f"fees:not_found={missing}"] if missing else [])
    return dropped, gaps


def with_compositions(env: Env, http: Http) -> tuple[int, list[str]]:
    """Compositions (funds.py) puis frais des fonds détenus : fichiers déposés, manques."""
    got, gaps = funds.run(env, http)
    more, missing = run(env, http)
    return got + more, gaps + missing
