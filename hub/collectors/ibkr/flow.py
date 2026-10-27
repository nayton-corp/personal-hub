"""Collecteur IBKR par le Flex Web Service (lot 6) : l'API officielle, en lecture seule.

Une requête Flex « Activity » préparée dans le Client Portal (Performance & Reports → Flex
Queries, voir docs/collectors.md) et un jeton Flex révocable suffisent : pas de navigateur, pas
d'identifiants IBKR. Deux appels : `SendRequest` (jeton + numéro de requête) rend un code de
référence, puis `GetStatement` rend le relevé XML une fois généré (quelques secondes). Le
relevé est déposé tel quel dans la boîte d'entrée ; seul le domaine Finance le lit.

Contrôle : `SendRequest` seul, qui vérifie le jeton et la requête sans rien déposer.
"""

from __future__ import annotations

import time
import urllib.parse
from collections.abc import Callable

from lxml import etree

from hub.collectors.base import Failure, Kind, Result
from hub.collectors.dropbox import is_flex
from hub.collectors.http import Http
from hub.collectors.runtime import Env

SERVICE = "https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService"
VERSION = "3"
POLL_SECONDS = 5
POLLS = 12
# codes d'erreur du Flex Web Service
AUTH = {"1011", "1012", "1013", "1014", "1015", "1016", "1020"}  # jeton, requête, compte
LATER = {"1001", "1003", "1004", "1005", "1006", "1007", "1008", "1009", "1018", "1019", "1021"}
IN_PROGRESS = "1019"


def _parse(raw: bytes) -> etree._Element:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)
    try:
        return etree.fromstring(raw, parser)
    except etree.XMLSyntaxError:
        raise Failure("invalid_file", "flex.response") from None


def _error(root: etree._Element, step: str) -> Failure:
    code = (root.findtext("ErrorCode") or "").strip()
    if code in AUTH:
        return Failure("auth_error", f"{step}:{code}")
    if code in LATER:
        return Failure("site_unavailable", f"{step}:{code}")
    return Failure("unknown", f"{step}:{code or 'status'}")


def send_request(env: Env, http: Http) -> tuple[str, str]:
    """(code de référence, adresse de GetStatement)."""
    service = env.cfg.urls.get("ibkr.service", SERVICE)
    query = urllib.parse.urlencode(
        {"t": env.secret("flex_token"), "q": env.secret("query_id"), "v": VERSION}
    )
    root = _parse(http.call(f"{service}/SendRequest?{query}", "flex.send"))
    if (root.findtext("Status") or "").strip() != "Success":
        raise _error(root, "flex.send")
    reference = (root.findtext("ReferenceCode") or "").strip()
    url = (root.findtext("Url") or f"{service}/GetStatement").strip()
    if not reference:
        raise Failure("unknown", "flex.send:no_reference")
    return reference, url


def get_statement(
    env: Env, http: Http, reference: str, url: str, sleep: Callable[[int], None]
) -> bytes:
    query = urllib.parse.urlencode({"t": env.secret("flex_token"), "q": reference, "v": VERSION})
    for _ in range(POLLS):
        raw = http.call(f"{url}?{query}", "flex.get")
        if is_flex(raw):
            return raw
        root = _parse(raw)
        if (root.findtext("ErrorCode") or "").strip() != IN_PROGRESS:
            raise _error(root, "flex.get")
        sleep(POLL_SECONDS)
    raise Failure("site_unavailable", "flex.get:timeout")


def run(
    env: Env,
    kind: Kind,
    http: Http | None = None,
    sleep: Callable[[int], None] = time.sleep,
) -> Result:
    http = http or Http()
    reference, url = send_request(env, http)
    if kind == "check":
        return Result("ok")
    sleep(POLL_SECONDS)  # IBKR conseille d'attendre avant le premier GetStatement
    data = get_statement(env, http, reference, url, sleep)
    if env.inbox.drop("ibkr-flex.xml", data, is_flex, step="flex.file"):
        return Result("ok", 1)
    return Result("nothing_new")
