"""Bot VIAC : documents nouveaux (PDF) et rapport hebdomadaire, vers la boîte d'entrée.

Le 2FA de VIAC demande un code : impossible dans un run planifié. Si la session a expiré, le run
s'arrête en `auth_error` (le collecteur passe en mode dégradé) sans jamais tenter de connexion ;
`hub-collector relogin viac` refait la connexion avec le code tapé au terminal. Les PDF déjà vus
sont reconnus par leur empreinte SHA-256. Le bot lit seulement la liste des documents (nom,
date) pour choisir quoi télécharger ; le contenu passe par les parseurs du domaine Finance.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable
from datetime import date, datetime, timedelta
from pathlib import Path

from hub.collectors.base import Failure, Kind, Result
from hub.collectors.browser import Browser
from hub.collectors.dropbox import is_pdf, safe
from hub.collectors.runtime import Env

SELECTORS = Path(__file__).with_name("selectors.toml")
PAGE_ROWS = 20
MAX_PAGES = 50


def open_documents(b: Browser) -> None:
    """Va sur Documents ; une session expirée montre le formulaire de connexion."""
    for attempt in range(3):
        b.goto(b.sel.site("documents"), "documents.open")
        state = b.wait_for(
            {
                "rows": lambda: b.find("documents.row", 0) is not None,
                "login": lambda: b.find("login.password", 0) is not None,
                "down": lambda: b.text_matches(b.sel.site("unavailable")),
            },
            10_000 + 5_000 * attempt,
        )
        if state == "rows":
            return
        if state == "login":
            raise Failure("auth_error", "session.expired")
        if state == "down":
            raise Failure("site_unavailable", "documents.open")
        b.page.evaluate("location.hash = '#/documents'")
    b.snap("documents.row")
    raise Failure("selector_missing", "documents.row")


def _rows(b: Browser) -> list[tuple[str, str, str, int]]:
    """(nom, portefeuille, date ISO, rang) des lignes visibles ; la date doit être lisible."""
    out = []
    cell = b.sel.get("documents.cell")
    for i, tr in enumerate(b.page.query_selector_all(b.sel.get("documents.row"))):
        cells = [
            c.strip() for c in tr.eval_on_selector_all(cell, "els => els.map(e => e.innerText)")
        ]
        if len(cells) < 3:
            continue
        try:
            on = datetime.strptime(cells[2], b.sel.site("date_format")).date().isoformat()  # noqa: DTZ007
        except ValueError:
            continue
        out.append((cells[0], re.sub(r"\s+", " ", cells[1]), on, i))
    return out


def fetch_documents(b: Browser, env: Env, since: str) -> tuple[int, str]:
    wanted = tuple(b.sel.items("wanted.prefixes"))
    seen_keys = set(env.memory.get("keys", []))
    files, newest = 0, since
    occurrences: Counter[str] = Counter()  # deux documents de même nom le même jour
    for _page in range(MAX_PAGES):
        rows = _rows(b)
        stop = False
        links = b.page.query_selector_all(b.sel.get("documents.row"))
        for name, portfolio, on, i in rows:
            if on < since:
                stop = True
                break
            base = f"{on}|{portfolio}|{name}"
            key = f"{base}|{occurrences[base]}"
            occurrences[base] += 1
            if key in seen_keys or not name.startswith(wanted):
                continue
            link = links[i].query_selector(b.sel.get("documents.link"))
            if link is None:
                continue
            b.downloads.clear()
            if "documents.link" not in b.sel.allowed:
                raise Failure("unknown", "whitelist:documents.link")
            link.click()
            data = _wait_download(b, 30_000)
            if data is None:
                continue  # téléchargement sans réponse : repris au prochain run
            if env.inbox.drop(f"viac-{on}-{safe(name)}.pdf", data, is_pdf, step="documents.file"):
                files += 1
            seen_keys.add(key)
            newest = max(newest, on)
        env.memory.put("keys", sorted(seen_keys)[-5000:])
        nxt = b.find("documents.next", 1_000)
        if stop or len(rows) < PAGE_ROWS or nxt is None or not nxt.is_enabled():
            break
        b.click("documents.next")
        b.page.wait_for_timeout(1_200)
    return files, newest


def _wait_download(b: Browser, timeout_ms: int) -> bytes | None:
    waited = 0
    while not b.downloads and waited < timeout_ms:
        b.page.wait_for_timeout(400)
        waited += 400
    if not b.downloads:
        return None
    d = b.downloads.pop(0)
    data = Path(d.path()).read_bytes()
    d.delete()
    return data


def request_report(b: Browser, env: Env, on: date) -> int:
    """Demande le rapport à la date `on` ; VIAC le livre tout de suite ou le dépose dans
    Documents, repris au run suivant."""
    b.click("report.button")
    field = b.require("report.date", 8_000)
    field.fill(on.strftime(b.sel.site("date_format")))
    b.page.keyboard.press("Tab")
    b.page.wait_for_timeout(600)
    create = b.find("report.create", 3_000)
    if create is None or not create.is_enabled():
        b.snap("report.create")
        raise Failure("selector_missing", "report.create")
    data = b.download_after("report.create", 60_000)
    b.page.keyboard.press("Escape")
    env.memory.put("report_requested_on", env.today.isoformat())
    if data is None:
        return 0
    return int(
        env.inbox.drop(f"viac-rapport-{on.isoformat()}.pdf", data, is_pdf, step="report.file")
    )


def run(env: Env, kind: Kind) -> Result:
    sel = env.selectors(SELECTORS)
    last = env.memory.get("last_date", "1900-01-01")
    since = (date.fromisoformat(last) - timedelta(days=env.cfg.viac_overlap_days)).isoformat()
    with env.browser(sel) as b:
        open_documents(b)
        if kind == "check":
            for name in ("documents.link", "report.button"):
                if b.find(name, 5_000) is None:
                    raise Failure("selector_missing", name)
            return Result("ok")
        files, newest = fetch_documents(b, env, since)
        env.memory.put("last_date", max(last, newest))
        requested = env.memory.get("report_requested_on")
        every = timedelta(days=env.cfg.viac_report_every_days)
        if requested is None or date.fromisoformat(requested) + every <= env.today:
            files += request_report(b, env, env.today - timedelta(days=1))
    return Result("ok", files) if files else Result("nothing_new")


def relogin(env: Env, ask_code: Callable[[], str]) -> Result:
    """Connexion assistée : identifiants des secrets, code 2FA tapé au terminal. Le profil
    reste dans le volume du collecteur ; le run de contrôle qui suit rend la reprise possible."""
    sel = env.selectors(SELECTORS)
    with env.browser(sel) as b:
        b.goto(sel.site("documents"), "login.open")
        state = b.wait_for(
            {
                "rows": lambda: b.find("documents.row", 0) is not None,
                "login": lambda: b.find("login.password", 0) is not None,
            },
            20_000,
        )
        if state == "rows":
            return Result("ok")
        if state is None:
            raise Failure("selector_missing", "login.password")
        user = b.find("login.user", 2_000)
        if user is not None:
            user.fill(env.secret("email"))
        password = b.require("login.password")
        password.fill(env.secret("password"))
        password.press("Enter")
        otp = b.wait_for(
            {
                "otp": lambda: b.find("login.otp", 0) is not None,
                "rows": lambda: b.find("documents.row", 0) is not None,
            },
            30_000,
        )
        if otp is None:
            b.snap("login.otp")
            raise Failure("selector_missing", "login.otp")
        if otp == "otp":
            code = ask_code()
            if not code:
                raise Failure("auth_error", "login.otp_empty")
            field = b.require("login.otp")
            field.fill(str(code).strip())
            field.press("Enter")
            b.settle()  # la navigation lancée par Entrée doit finir avant d'aller ailleurs
        open_documents(b)  # attend la liste ; formulaire à nouveau : code refusé
        b.page.wait_for_timeout(2_000)  # laisse l'app enregistrer sa session dans le profil
    return Result("ok")
