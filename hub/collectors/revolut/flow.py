"""Collecteur Revolut par Enable Banking (décision du 27/10/2026).

- Liaison (`hub-collector revolut link`) : URL d'autorisation affichée, retour du navigateur sur
  `/api/collectors/revolut/callback`, session créée, puis reprise complète de l'historique tout
  de suite : Revolut ne donne tout l'historique que dans les 5 minutes qui suivent le
  consentement, ensuite 90 jours seulement.
- Synchro planifiée : J-10 à aujourd'hui pour chaque compte, au plus 4 par jour (limite Revolut
  sans l'utilisateur). Un fichier `hub.revolut.v1` par compte, déposé seulement s'il a changé.
- Consentement expiré ou révoqué : `auth_error`, mode dégradé, nouvelle liaison. Une alerte part
  quelques jours avant l'échéance.

Le collecteur ne lit pas les écritures : il recopie la réponse de la banque dans un fichier que
seul le parseur du domaine Finance interprète.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import time
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any

from hub.collectors.base import Failure, Kind, Result
from hub.collectors.dropbox import is_revolut_json
from hub.collectors.revolut.enable_banking import EnableBanking
from hub.collectors.runtime import Env
from hub.core.clock import iso, now_iso, utcnow

FORMAT = "hub.revolut.v1"
HISTORY_FROM = "2015-01-01"  # Revolut n'existe pas avant : « tout l'historique »
LINK_POLL_SECONDS = 2
# champs du compte gardés dans le fichier (l'uid change à chaque consentement : il n'y est pas)
ACCOUNT_FIELDS = (
    "account_id",
    "currency",
    "name",
    "product",
    "cash_account_type",
    "identification_hash",
    "usage",
    "details",
)


def client(env: Env) -> EnableBanking:
    return EnableBanking(
        env.cfg.revolut.api_url, env.secret("application_id"), env.secret("private_key")
    )


def _syncs_today(env: Env) -> int:
    counts: dict[str, int] = env.memory.get("syncs", {})
    return int(counts.get(env.today.isoformat(), 0))


def _count_sync(env: Env) -> None:
    counts: dict[str, int] = env.memory.get("syncs", {})
    day = env.today.isoformat()
    env.memory.put("syncs", {day: int(counts.get(day, 0)) + 1})


def _document(
    account: dict[str, Any],
    balances: list[dict[str, Any]],
    transactions: list[dict[str, Any]],
    date_from: str,
    date_to: str,
    full: bool,
) -> dict[str, Any]:
    return {
        "format": FORMAT,
        "source": "enable_banking",
        "fetched_at": now_iso(),
        "date_from": date_from,
        "date_to": date_to,
        "full_history": full,
        "account": {k: account[k] for k in ACCOUNT_FIELDS if k in account},
        "balances": balances,
        "transactions": transactions,
    }


def _digest(doc: dict[str, Any]) -> str:
    """Empreinte du contenu (compte, soldes, écritures) : rien de neuf, rien de déposé."""
    stable = {k: doc[k] for k in ("account", "balances", "transactions")}
    return hashlib.sha256(json.dumps(stable, sort_keys=True).encode()).hexdigest()


def sync(env: Env, eb: EnableBanking, date_from: str, *, full: bool = False) -> int:
    accounts: list[dict[str, Any]] = env.memory.get("accounts", [])
    if not accounts:
        raise Failure("auth_error", "consent.no_account")
    digests: dict[str, str] = env.memory.get("digests", {})
    date_to = env.today.isoformat()
    files = 0
    _count_sync(env)
    for account in accounts:
        uid = str(account["uid"])
        doc = _document(
            account,
            eb.balances(uid),
            eb.transactions(uid, date_from, date_to),
            date_from,
            date_to,
            full,
        )
        key = str(account.get("identification_hash") or uid)
        digest = _digest(doc)
        if digests.get(key) == digest:
            continue
        data = json.dumps(doc, ensure_ascii=False, sort_keys=True).encode()
        name = f"revolut-{key[:12]}.json"
        if env.inbox.drop(name, data, is_revolut_json, step="eb.file"):
            files += 1
        digests[key] = digest
    env.memory.put("digests", digests)
    return files


def _consent(env: Env) -> tuple[str, str]:
    session_id = env.memory.get("session_id")
    valid_until = env.memory.get("valid_until")
    if not session_id or not valid_until:
        raise Failure("auth_error", "consent.missing")
    if valid_until <= now_iso():
        raise Failure("auth_error", "consent.expired")
    return str(session_id), str(valid_until)


def _warn_expiry(env: Env, valid_until: str) -> None:
    left = datetime.fromisoformat(valid_until.replace("Z", "+00:00")) - utcnow()
    soon = left <= timedelta(days=env.cfg.revolut.warn_days)
    if soon and env.memory.get("warned") != valid_until and env.notify("consent_expiring"):
        env.memory.put("warned", valid_until)


def run(env: Env, kind: Kind, eb: EnableBanking | None = None) -> Result:
    session_id, valid_until = _consent(env)
    eb = eb or client(env)
    if kind == "check":
        status = eb.session(session_id).get("status")
        if status != "AUTHORIZED":
            raise Failure("auth_error", f"consent.{str(status).lower()}")
        return Result("ok")
    _warn_expiry(env, valid_until)
    if _syncs_today(env) >= env.cfg.revolut.max_syncs_per_day:
        return Result("nothing_new", 0, "quota.day")
    since = (env.today - timedelta(days=env.cfg.revolut.overlap_days)).isoformat()
    files = sync(env, eb, since)
    return Result("ok", files) if files else Result("nothing_new")


def _valid_until(env: Env, eb: EnableBanking) -> str:
    days = env.cfg.revolut.consent_days
    for a in eb.aspsps(env.cfg.revolut.aspsp_country):
        if a.get("name") == env.cfg.revolut.aspsp_name and a.get("maximum_consent_validity"):
            # un jour sous le maximum : pile au maximum, Revolut répond invalid_request une fois
            # le consentement donné (la validité court depuis la validation, pas la demande)
            days = min(days, int(a["maximum_consent_validity"]) // 86_400 - 1)
    return iso(datetime.now(UTC) + timedelta(days=max(days, 1)))


def link(
    env: Env,
    redirect_url: str,
    show: Callable[[str], None],
    eb: EnableBanking | None = None,
    *,
    wait_s: int = 15 * 60,
    sleep: Callable[[int], None] = time.sleep,
) -> Result:
    """Nouvelle liaison, puis reprise complète dans la foulée (fenêtre de 5 minutes)."""
    if env.client is None:
        raise Failure("unknown", "link:no_hub")
    eb = eb or client(env)
    state = secrets.token_urlsafe(24)
    valid_until = _valid_until(env, eb)
    url = eb.start_auth(
        aspsp=env.cfg.revolut.aspsp_name,
        country=env.cfg.revolut.aspsp_country,
        valid_until=valid_until,
        redirect_url=redirect_url,
        state=state,
        psu_type=env.cfg.revolut.psu_type,
    )
    env.client.register_link(env.name, state)
    show(url)
    code = None
    waited = 0
    while code is None:
        code = env.client.take_link(env.name, state)
        if code is None:
            if waited >= wait_s:
                raise Failure("auth_pending_timeout", "link.callback")
            sleep(LINK_POLL_SECONDS)
            waited += LINK_POLL_SECONDS
    session = eb.create_session(code)
    accounts = [a for a in session.get("accounts", []) if isinstance(a, dict) and a.get("uid")]
    if not accounts:
        raise Failure("auth_error", "consent.no_account")
    access = session.get("access") or {}
    env.memory.put("session_id", session["session_id"])
    env.memory.put("valid_until", str(access.get("valid_until") or valid_until))
    env.memory.put("accounts", accounts)
    env.memory.put("digests", {})
    env.memory.put("linked_at", now_iso())
    env.memory.save()
    files = sync(env, eb, HISTORY_FROM, full=True)
    return Result("ok", files)


def accounts_summary(env: Env) -> list[dict[str, Any]]:
    """Comptes reliés, sans solde ni écriture : devise, type, nom de produit."""
    out = []
    for a in env.memory.get("accounts", []):
        out.append(
            {
                "currency": a.get("currency"),
                "type": a.get("cash_account_type"),
                "product": a.get("product") or a.get("name"),
                "key": str(a.get("identification_hash") or a.get("uid"))[:12],
            }
        )
    return out


def days_left(env: Env) -> int | None:
    valid_until = env.memory.get("valid_until")
    if not valid_until:
        return None
    end = datetime.fromisoformat(str(valid_until).replace("Z", "+00:00")).date()
    return (end - date.today()).days  # noqa: DTZ011 - ordre de grandeur pour l'affichage
