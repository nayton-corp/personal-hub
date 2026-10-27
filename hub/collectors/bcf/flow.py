"""Bot BCF : connexion, validation du push, export camt.053 de tous les comptes.

Une fonction par étape, chacune avec son délai et son type d'échec. Le bot exporte toujours
avec « mouvements déjà exportés » coché et une date de départ à J-10 : il ne dépend jamais de
la mémoire d'export de la banque, et le dédoublonnage absorbe le recouvrement. Il ne lit rien
à l'écran : il repère seulement des états (connecté, refusé, rien à exporter).
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from hub.collectors.base import Failure, Kind, Result
from hub.collectors.browser import Browser
from hub.collectors.dropbox import is_camt_export
from hub.collectors.runtime import Env

SELECTORS = Path(__file__).with_name("selectors.toml")
LOGIN_SECONDS = 180  # attente du push sur le téléphone
DOWNLOAD_SECONDS = 60
REFUSAL_MS = 3_000  # délai pour reconnaître un refus avant d'envoyer la notification


def login(b: Browser, env: Env) -> None:
    sel = b.sel
    b.goto(sel.site("url"), "login.open")
    state = b.wait_for(
        {
            "in": lambda: b.text_matches(sel.site("logged_in")),
            "form": lambda: b.find("login.password", 0) is not None,
            "down": lambda: b.text_matches(sel.site("unavailable")),
        },
        15_000,
    )
    if state == "in":
        return
    if state == "down":
        raise Failure("site_unavailable", "login.open")
    if state is None:
        b.snap("login.password")
        raise Failure("selector_missing", "login.password")
    password = b.require("login.password")
    contract = b.find("login.contract", 2_000)
    if contract is not None:
        contract.fill(env.secret("contract"))
    password.fill(env.secret("password"))
    password.press("Enter")
    # un refus s'affiche vite : on le guette avant de déranger le téléphone
    early = b.wait_for(
        {
            "refused": lambda: b.text_matches(sel.site("auth_refused")),
            "in": lambda: b.text_matches(sel.site("logged_in")),
        },
        REFUSAL_MS,
    )
    if early == "refused":
        b.snap("login.refused")
        raise Failure("auth_error", "login.refused")
    if early == "in":
        return
    env.notify("auth_pending")
    state = b.wait_for(
        {
            "in": lambda: b.text_matches(sel.site("logged_in")),
            "refused": lambda: b.text_matches(sel.site("auth_refused")),
        },
        LOGIN_SECONDS * 1000,
    )
    if state == "refused":
        b.snap("login.refused")
        raise Failure("auth_error", "login.refused")
    if state is None:
        raise Failure("auth_pending_timeout", "login.push")


def open_statement(b: Browser) -> None:
    if b.find("statement.link", 10_000) is not None:
        b.click("statement.link")
    elif b.find("statement.all_entries", 5_000) is not None:
        b.click("statement.all_entries")
    else:
        b.snap("statement.link")
        raise Failure("selector_missing", "statement.link")


def open_export(b: Browser) -> None:
    b.click("export.button", 15_000)
    if b.frame_of("export.form", 10_000) is None:
        b.snap("export.form")
        raise Failure("selector_missing", "export.form")


def fill_form(b: Browser, since: str) -> None:
    frame = b.frame_of("export.form", 2_000)
    if frame is None:
        raise Failure("selector_missing", "export.form")
    camt = frame.query_selector(b.sel.get("export.format_camt"))
    if camt is None:
        raise Failure("selector_missing", "export.format_camt")
    camt.check()
    every = frame.query_selector(b.sel.get("export.all_accounts"))
    if every is not None and every.is_enabled():
        every.check()
    fetched = frame.query_selector(b.sel.get("export.already_fetched"))
    if fetched is None:
        raise Failure("selector_missing", "export.already_fetched")
    if not fetched.is_checked():
        fetched.check()
    field = frame.query_selector(b.sel.get("export.date_from"))
    if field is None:
        raise Failure("selector_missing", "export.date_from")
    for _ in range(3):
        field.click()
        b.page.keyboard.press("Control+A")  # Linux : Control, pas Meta comme sur le Mac
        b.page.keyboard.press("Backspace")
        b.page.keyboard.type(since, delay=40)
        b.page.keyboard.press("Enter")
        b.page.wait_for_timeout(500)
        b.page.keyboard.press("Tab")
        b.page.wait_for_timeout(300)
        if field.get_attribute("date-value"):
            return
        field.evaluate(
            "(el, v) => { el.value = v; for (const t of ['input', 'change', 'blur'])"
            " el.dispatchEvent(new Event(t, {bubbles: true})); }",
            since,
        )
        b.page.wait_for_timeout(300)
        if field.get_attribute("date-value"):
            return
    # sans date de départ, la banque reprendrait sa mémoire d'export : on s'arrête
    b.snap("export.date_from")
    raise Failure("selector_missing", "export.date_from")


def logout(b: Browser) -> None:
    try:
        if b.find("logout.button", 2_000) is not None:
            b.click("logout.button")
            b.page.wait_for_timeout(1_000)
    except Failure:
        pass  # la session expirera d'elle-même


def run(env: Env, kind: Kind) -> Result:
    sel = env.selectors(SELECTORS)
    since = (env.today - timedelta(days=env.cfg.bcf_overlap_days)).strftime(sel.site("date_format"))
    with env.browser(sel) as b:
        try:
            return _run(b, env, kind, since)
        except Failure as f:
            b.snap(f.detail)
            raise


def _run(b: Browser, env: Env, kind: Kind, since: str) -> Result:
    login(b, env)
    open_statement(b)
    open_export(b)
    if kind == "check":
        for name in ("export.format_camt", "export.already_fetched", "export.date_from"):
            if not b.exists(name, 2_000):
                raise Failure("selector_missing", name)
        if b.find("export.download", 2_000) is None:
            raise Failure("selector_missing", "export.download")
        b.page.keyboard.press("Escape")
        logout(b)
        return Result("ok")
    fill_form(b, since)
    b.page.wait_for_timeout(500)

    def nothing_shown() -> bool:
        return b.text_matches(b.sel.site("nothing_to_export"))

    data = b.download_after("export.download", DOWNLOAD_SECONDS * 1000, nothing_shown)
    if data is None:
        nothing = nothing_shown()
        logout(b)
        if nothing:
            return Result("nothing_new")
        raise Failure("unknown", "export.download:timeout")
    suffix = "zip" if data[:2] == b"PK" else "xml"
    fresh = env.inbox.drop(f"bcf-camt053.{suffix}", data, is_camt_export, step="export.file")
    logout(b)
    return Result("ok", 1) if fresh else Result("nothing_new")
