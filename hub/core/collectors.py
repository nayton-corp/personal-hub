"""État des collecteurs dans `core.db` (lot 5, spécification section 8).

Un état par connexion (`connections`, G4) : le nom d'un collecteur est l'identifiant de la
connexion qu'il exécute. Un collecteur ne fait que déposer des fichiers dans la boîte d'entrée
et déclarer chaque run ici. Trois modes : `enabled` (il tourne selon son planning), `degraded`
(il ne tourne plus seul, l'app invite à l'import manuel) et `disabled` (coupé par toi). Le retour
à `enabled` est toujours manuel, et seulement si le dernier run (un contrôle, en pratique) a
réussi : plusieurs échecs de connexion d'affilée peuvent faire bloquer l'accès e-banking.

Le détail d'un run ne contient que l'étape et le nom du sélecteur, jamais de contenu.
"""

from __future__ import annotations

import re
import secrets as pysecrets
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Literal

from sqlalchemy import Connection, text

from hub.core import connections
from hub.core.clock import iso, local_tz, now_iso, parse_iso, utcnow
from hub.core.coredb import audit
from hub.core.errors import Problem
from hub.core.ids import new_id
from hub.core.notify import Message, Priority

Outcome = Literal[
    "ok",
    "nothing_new",
    "auth_pending_timeout",
    "site_unavailable",
    "selector_missing",
    "invalid_file",
    "auth_error",
    "unknown",
]
Mode = Literal["enabled", "degraded", "disabled"]
SUCCESS = frozenset({"ok", "nothing_new"})
HARD = frozenset({"selector_missing", "invalid_file", "auth_error", "unknown"})
DEGRADE_AFTER = 2  # échecs durs de suite (auth_error : tout de suite)
SITE_ALERT_AFTER = 3  # site indisponible de suite
LINK_MINUTES = 15
_DETAIL = re.compile(r"[^a-z0-9_.:\- ]")


@dataclass(frozen=True)
class Run:
    kind: Literal["run", "check"]
    outcome: Outcome
    started_at: str
    ended_at: str
    files: int = 0
    detail: str | None = None


@dataclass
class State:
    name: str
    label: str
    connector: str
    ready: bool
    mode: str
    consecutive_failures: int
    since: str
    check_requested_at: str | None
    last_run: dict[str, Any] | None = None
    last_success_at: str | None = None
    link_requested_at: str | None = None
    link_url: str | None = None
    link_url_at: str | None = None

    @property
    def open_link(self) -> str | None:
        """L'adresse d'autorisation, tant que le retour peut encore être accepté."""
        if not self.link_url or not self.link_url_at:
            return None
        if utcnow() - parse_iso(self.link_url_at) > timedelta(minutes=LINK_MINUTES):
            return None
        return self.link_url

    def public(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "connector": self.connector,
            "ready": self.ready,
            "mode": self.mode,
            "consecutive_failures": self.consecutive_failures,
            "since": self.since,
            "check_requested": self.check_requested_at is not None,
            "last_run": self.last_run,
            "last_success_at": self.last_success_at,
            "can_enable": self.mode != "enabled" and _clean(self.last_run),
            "link_requested": self.link_requested_at is not None,
            "link_url": self.open_link,
        }


@dataclass
class Recorded:
    state: State
    alerts: list[Message] = field(default_factory=list)


def _clean(last_run: dict[str, Any] | None) -> bool:
    return last_run is None or last_run["outcome"] in SUCCESS


def label(conn: Connection, name: str) -> str:
    return connections.require(conn, name).label


def clean_detail(detail: str | None) -> str | None:
    """Étape et sélecteur seulement : minuscules, chiffres et `_.:- `, 120 caractères."""
    if not detail:
        return None
    return _DETAIL.sub("?", detail.lower())[:120]


def _ensure(conn: Connection, name: str) -> connections.Connection:
    # l'écriture d'abord : une transaction qui lit puis écrit ne peut pas attendre le verrou
    # (« database is locked » quand les deux services appellent l'API à la même seconde)
    conn.execute(
        text(
            "INSERT INTO collector_state (collector, mode, consecutive_failures, since) "
            "SELECT id, 'enabled', 0, :at FROM connections WHERE id = :c "
            "ON CONFLICT (collector) DO NOTHING"
        ),
        {"c": name, "at": now_iso()},
    )
    return connections.require(conn, name)


def _run_row(r: Any) -> dict[str, Any]:
    return {
        "id": r.id,
        "kind": r.kind,
        "outcome": r.outcome,
        "started_at": r.started_at,
        "ended_at": r.ended_at,
        "files": r.files,
        "detail": r.detail,
    }


def runs(conn: Connection, name: str, limit: int = 20) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            "SELECT id, kind, outcome, started_at, ended_at, files, detail FROM collector_runs "
            "WHERE collector = :c ORDER BY started_at DESC, id DESC LIMIT :n"
        ),
        {"c": name, "n": limit},
    ).fetchall()
    return [_run_row(r) for r in rows]


def get(conn: Connection, name: str) -> State:
    connection = _ensure(conn, name)
    row = conn.execute(
        text(
            "SELECT mode, consecutive_failures, since, check_requested_at, link_requested_at, "
            "link_url, link_url_at FROM collector_state WHERE collector = :c"
        ),
        {"c": name},
    ).one()
    recent = runs(conn, name, 1)
    success = conn.execute(
        text(
            "SELECT max(ended_at) FROM collector_runs WHERE collector = :c "
            "AND outcome IN ('ok', 'nothing_new')"
        ),
        {"c": name},
    ).scalar_one()
    return State(
        name,
        connection.label,
        connection.connector,
        connection.ready,
        row.mode,
        row.consecutive_failures,
        row.since,
        row.check_requested_at,
        recent[0] if recent else None,
        success,
        row.link_requested_at,
        row.link_url,
        row.link_url_at,
    )


def list_all(conn: Connection) -> list[State]:
    conn.execute(
        text(
            "INSERT INTO collector_state (collector, mode, consecutive_failures, since) "
            "SELECT id, 'enabled', 0, :at FROM connections WHERE true "
            "ON CONFLICT (collector) DO NOTHING"
        ),
        {"at": now_iso()},
    )
    return [get(conn, c.id) for c in connections.list_all(conn)]


def _set(conn: Connection, name: str, **values: Any) -> None:
    sets = ", ".join(f"{k} = :{k}" for k in values)
    conn.execute(
        text(f"UPDATE collector_state SET {sets} WHERE collector = :c"),  # noqa: S608 - clés fixes
        {**values, "c": name},
    )


def _streak(conn: Connection, name: str, outcome: str) -> int:
    count = 0
    for r in runs(conn, name, SITE_ALERT_AFTER + 1):
        if r["outcome"] != outcome:
            break
        count += 1
    return count


def _first_today(conn: Connection, name: str, outcome: str, run_id: str) -> bool:
    tz = local_tz()
    today = utcnow().astimezone(tz).date()
    for r in runs(conn, name, 20):
        if r["id"] == run_id:
            continue
        if parse_iso(r["started_at"]).astimezone(tz).date() != today:
            break
        if r["outcome"] == outcome:
            return False
    return True


# les notifications des collecteurs ouvrent la page des sources dans l'app
SOURCES_CLICK = "/#sources"


TEXTS: dict[str, tuple[Priority, str]] = {
    "auth_error": ("urgent", "Connexion refusée."),
    "selector_missing": ("high", "Écran inattendu ({detail})."),
    "unknown": ("high", "Erreur inattendue ({detail})."),
    "invalid_file": ("high", "Fichier téléchargé non conforme, mis en quarantaine."),
    "auth_pending_timeout": ("default", "Connexion non validée à temps, nouvel essai demain."),
    "site_unavailable": ("default", "Site indisponible trois fois de suite."),
}


def _alert(name_label: str, outcome: str, detail: str | None, degraded: bool) -> Message:
    priority, body = TEXTS[outcome]
    body = body.format(detail=detail or "?")
    if degraded:
        body += " Collecte suspendue : import manuel en attendant, puis contrôle depuis l'app."
    return Message(f"Collecte {name_label} : action requise", body, priority, click=SOURCES_CLICK)


def record(conn: Connection, name: str, run: Run, by: str) -> Recorded:
    """Inscrit un run et applique la table des échecs (spécification, section 8)."""
    name_label = _ensure(conn, name).label
    detail = clean_detail(run.detail)
    run_id = new_id()
    conn.execute(
        text(
            "INSERT INTO collector_runs (id, collector, kind, started_at, ended_at, outcome, "
            "files, detail) VALUES (:id, :c, :k, :s, :e, :o, :f, :d)"
        ),
        {
            "id": run_id,
            "c": name,
            "k": run.kind,
            "s": run.started_at,
            "e": run.ended_at,
            "o": run.outcome,
            "f": run.files,
            "d": detail,
        },
    )
    before = get(conn, name)
    changes: dict[str, Any] = {}
    if run.kind == "check":
        changes["check_requested_at"] = None
    alerts: list[Message] = []
    if run.outcome in SUCCESS:
        changes["consecutive_failures"] = 0
    elif run.outcome in HARD:
        failures = before.consecutive_failures + 1
        changes["consecutive_failures"] = failures
        degrade = before.mode == "enabled" and (
            run.outcome == "auth_error" or failures >= DEGRADE_AFTER
        )
        if degrade:
            changes.update(mode="degraded", since=now_iso())
        if before.mode != "disabled":
            alerts.append(_alert(name_label, run.outcome, detail, degrade))
    elif before.mode != "disabled" and (
        (run.outcome == "auth_pending_timeout" and _first_today(conn, name, run.outcome, run_id))
        or (
            run.outcome == "site_unavailable"
            and _streak(conn, name, run.outcome) == SITE_ALERT_AFTER
        )
    ):
        alerts.append(_alert(name_label, run.outcome, detail, False))
    if changes:
        _set(conn, name, **changes)
    if changes.get("mode") == "degraded":
        audit(conn, by, "collector.degraded", f"collector:{name}", run.outcome)
    return Recorded(get(conn, name), alerts)


def set_mode(conn: Connection, name: str, mode: Mode, by: str) -> State:
    state = get(conn, name)
    if mode == state.mode:
        return state
    if mode == "enabled" and not _clean(state.last_run):
        raise Problem("collector.check_required")
    if mode == "degraded":
        raise Problem("validation.params", "le mode dégradé est posé par les échecs seulement")
    _set(conn, name, mode=mode, since=now_iso(), consecutive_failures=0)
    audit(conn, by, f"collector.{mode}", f"collector:{name}", "ok")
    return get(conn, name)


def request_check(conn: Connection, name: str, by: str) -> State:
    _ensure(conn, name)
    _set(conn, name, check_requested_at=now_iso())
    audit(conn, by, "collector.check_requested", f"collector:{name}", "ok")
    return get(conn, name)


def request_link(conn: Connection, name: str, by: str) -> State:
    """Nouveau consentement demandé depuis l'app : le service qui exécute la connexion ouvre
    l'autorisation dans la minute et remonte l'adresse à ouvrir."""
    connection = _ensure(conn, name)
    if connection.connector != "enable_banking":
        raise Problem("validation.params", "seule une connexion Enable Banking se lie ainsi")
    if not connection.ready:
        raise Problem("validation.params", "secrets de la connexion à donner d'abord")
    _set(conn, name, link_requested_at=now_iso(), link_url=None, link_url_at=None)
    audit(conn, by, "collector.link_requested", f"collector:{name}", "ok")
    return get(conn, name)


def set_link_url(conn: Connection, name: str, url: str | None) -> State:
    """Le collecteur a pris la demande : l'adresse à ouvrir, ou rien (liaison finie)."""
    _ensure(conn, name)
    if url is not None and (not url.startswith("https://") or len(url) > 4000):
        raise Problem("validation.params", "adresse d'autorisation invalide")
    _set(
        conn,
        name,
        link_requested_at=None,
        link_url=url,
        link_url_at=now_iso() if url else None,
    )
    return get(conn, name)


def auth_pending(name_label: str) -> Message:
    """Notification envoyée quand le bot attend ta validation sur le téléphone."""
    return Message(
        f"Collecte {name_label} : connexion à valider",
        "Valide la connexion sur ton téléphone (3 minutes).",
        "high",
        click=SOURCES_CLICK,
    )


# --- liaison d'un consentement (Revolut, Enable Banking) ------------------------------------


def register_link(conn: Connection, name: str, state: str) -> str:
    """Le collecteur annonce le `state` de son autorisation ; le retour du navigateur sera
    accepté pendant quelques minutes seulement."""
    connections.require(conn, name)
    if not re.fullmatch(r"[A-Za-z0-9_-]{16,100}", state):
        raise Problem("validation.params", "state invalide")
    now = utcnow()
    expires = iso(now + timedelta(minutes=LINK_MINUTES))
    conn.execute(
        text(
            "INSERT INTO collector_links (state, collector, created_at, expires_at) "
            "VALUES (:s, :c, :at, :exp)"
        ),
        {"s": state, "c": name, "at": iso(now), "exp": expires},
    )
    return expires


def receive_code(conn: Connection, name: str, state: str, code: str) -> bool:
    """Retour du navigateur après le consentement : garde le code pour le collecteur."""
    if not code or len(code) > 2000:
        return False
    res = conn.execute(
        text(
            "UPDATE collector_links SET code = :code, received_at = :at WHERE state = :s "
            "AND collector = :c AND code IS NULL AND expires_at > :at"
        ),
        {"code": code, "at": now_iso(), "s": state, "c": name},
    )
    return res.rowcount == 1


def take_code(conn: Connection, name: str, state: str) -> str | None:
    """Rend le code une seule fois ; `None` tant que le navigateur n'est pas revenu."""
    row = conn.execute(
        text("SELECT code, expires_at FROM collector_links WHERE state = :s AND collector = :c"),
        {"s": state, "c": name},
    ).first()
    if row is None:
        raise Problem("collector.link_unknown")
    if row.code is None:
        if row.expires_at <= now_iso():
            conn.execute(text("DELETE FROM collector_links WHERE state = :s"), {"s": state})
            raise Problem("collector.link_unknown", "liaison expirée")
        return None
    conn.execute(text("DELETE FROM collector_links WHERE state = :s"), {"s": state})
    return str(row.code)


def purge_links(conn: Connection) -> int:
    sql = text("DELETE FROM collector_links WHERE expires_at <= :at")
    res = conn.execute(sql, {"at": now_iso()})
    return res.rowcount


def new_state() -> str:
    return pysecrets.token_urlsafe(24)
