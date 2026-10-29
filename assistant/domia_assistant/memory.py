"""La mémoire du foyer (spec §9), une base SQLite sur la machine IA : les notes confiées (avec qui l'a dit, et pour qui
si elle est personnelle), les synonymes appris pour la voie rapide, les conversations résumées (90 jours), les
remarques dites et les refus (un « non » rend un sujet plus rare : une semaine de silence, puis le double).

Une voix sans personne (un micro de pièce, lot 2) ne lit que les notes du foyer, jamais les notes personnelles."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

CONVERSATION_DAYS = 90
FIRST_SILENCE = timedelta(days=7)

SCHEMA = """
CREATE TABLE IF NOT EXISTS notes (
  id INTEGER PRIMARY KEY, text TEXT NOT NULL, person TEXT, said_by TEXT, at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS synonyms (
  phrase TEXT PRIMARY KEY, kind TEXT NOT NULL, target TEXT NOT NULL, said_by TEXT, at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS conversations (
  id INTEGER PRIMARY KEY, at TEXT NOT NULL, person TEXT, room TEXT, text TEXT NOT NULL, answer TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS remarks (
  subject TEXT PRIMARY KEY, said_at TEXT, refusals INTEGER NOT NULL DEFAULT 0, quiet_until TEXT);
CREATE TABLE IF NOT EXISTS engagements (
  id INTEGER PRIMARY KEY, kind TEXT NOT NULL, question TEXT NOT NULL, offer TEXT NOT NULL, state TEXT NOT NULL,
  person TEXT, offered_at TEXT NOT NULL, expires TEXT NOT NULL, armed_at TEXT, outcome TEXT);
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY, at TEXT NOT NULL, title TEXT NOT NULL, text TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS settings_changes (
  id INTEGER PRIMARY KEY, person TEXT, at TEXT NOT NULL, revision INTEGER NOT NULL, changes TEXT NOT NULL,
  undo TEXT NOT NULL, summary TEXT NOT NULL, state TEXT NOT NULL, applied_at TEXT, undoes INTEGER, undone_by INTEGER);
"""

# Colonnes venues après la première version d'une table : ajoutées à l'ouverture d'une base existante.
ADDED = (("conversations", "voice", "INTEGER NOT NULL DEFAULT 0"), ("conversations", "done", "TEXT"))

# Les états d'un engagement (spec « préparer demain » §6) : proposé, accepté (un « oui »), puis joué, pas joué (sa
# condition ne tenait plus), refusé, annulé ou expiré.
OFFERED, ACCEPTED, DONE, SKIPPED, REFUSED, CANCELLED, EXPIRED = (
    "OFFERED",
    "ACCEPTED",
    "DONE",
    "SKIPPED",
    "REFUSED",
    "CANCELLED",
    "EXPIRED",
)


def now_utc() -> datetime:
    return datetime.now(UTC)


class Memory:
    def __init__(self, path: Path | str):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        for table, column, kind in ADDED:
            if column not in {r["name"] for r in self.db.execute(f"PRAGMA table_info({table})")}:
                self.db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")
        self.db.commit()
        self.lock = threading.Lock()

    def _exec(self, sql: str, args=()) -> sqlite3.Cursor:
        with self.lock:
            cur = self.db.execute(sql, args)
            self.db.commit()
            return cur

    # notes
    def remember(self, text: str, said_by: str | None, personal: bool = False, at: datetime | None = None) -> int:
        """Une note du foyer, ou personnelle (seule sa personne la relit) ; rendue avec son id pour l'oublier."""
        if personal and not said_by:
            raise ValueError("une note personnelle a besoin de sa personne")
        cur = self._exec(
            "INSERT INTO notes (text, person, said_by, at) VALUES (?, ?, ?, ?)",
            (text.strip(), said_by if personal else None, said_by, (at or now_utc()).isoformat()),
        )
        return int(cur.lastrowid or 0)

    def recall(self, question: str, person: str | None, limit: int = 8) -> list[dict]:
        """Les notes qui partagent des mots avec la question, les plus récentes d'abord ; celles du foyer et celles de
        la personne qui demande."""
        terms = {w for w in _words(question) if len(w) > 2}
        rows = self._exec(
            "SELECT * FROM notes WHERE person IS NULL OR person = ? ORDER BY at DESC", (person or "\x00",)
        ).fetchall()
        scored = []
        for r in rows:
            score = len(terms & set(_words(r["text"])))
            if score or not terms:
                scored.append((score, dict(r)))
        scored.sort(key=lambda s: -s[0])
        return [s[1] for s in scored[:limit]]

    def about(self, person: str) -> list[dict]:
        """« Qu'est-ce que tu sais de moi ? » : les notes dites par la personne ou à elle seule."""
        rows = self._exec(
            "SELECT * FROM notes WHERE person = ? OR said_by = ? ORDER BY at", (person, person)
        ).fetchall()
        return [dict(r) for r in rows]

    def forget(self, note_id: int, person: str | None) -> bool:
        """« Oublie ça » : une note du foyer, ou une note de la personne qui demande ; jamais celle d'un autre."""
        cur = self._exec(
            "DELETE FROM notes WHERE id = ? AND (person IS NULL OR person = ?)", (note_id, person or "\x00")
        )
        return cur.rowcount > 0

    # synonymes de la voie rapide
    def learn(self, phrase: str, kind: str, target: str, said_by: str | None) -> None:
        self._exec(
            "INSERT OR REPLACE INTO synonyms (phrase, kind, target, said_by, at) VALUES (?, ?, ?, ?, ?)",
            (phrase.strip().lower(), kind, target, said_by, now_utc().isoformat()),
        )

    def synonyms(self) -> dict[str, tuple[str, str]]:
        return {r["phrase"]: (r["kind"], r["target"]) for r in self._exec("SELECT * FROM synonyms").fetchall()}

    # conversations
    def log(
        self,
        person: str | None,
        room: str | None,
        text: str,
        answer: str,
        at: datetime | None = None,
        voice: bool = False,
        done: list[str] | None = None,
    ) -> None:
        at = at or now_utc()
        self._exec(
            "INSERT INTO conversations (at, person, room, text, answer, voice, done) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                at.isoformat(),
                person,
                room,
                text[:500],
                answer[:500],
                int(voice),
                json.dumps(done, ensure_ascii=False) if done else None,
            ),
        )
        self._exec("DELETE FROM conversations WHERE at < ?", ((at - timedelta(days=CONVERSATION_DAYS)).isoformat(),))

    def recent(self, person: str | None, limit: int = 6) -> list[dict]:
        rows = self._exec(
            "SELECT * FROM conversations WHERE person IS ? ORDER BY at DESC LIMIT ?", (person, limit)
        ).fetchall()
        return [dict(r) for r in reversed(rows)]

    # ce que l'assistant dit de lui-même (spec de l'écran §7) : le plan du soir, une remarque, un engagement tenu
    def message(self, title: str, text: str, at: datetime | None = None) -> None:
        at = at or now_utc()
        self._exec(
            "INSERT INTO messages (at, title, text) VALUES (?, ?, ?)", (at.isoformat(), title[:120], text[:2000])
        )
        self._exec("DELETE FROM messages WHERE at < ?", ((at - timedelta(days=CONVERSATION_DAYS)).isoformat(),))

    def messages(self, since: datetime) -> list[dict]:
        rows = self._exec("SELECT * FROM messages WHERE at >= ? ORDER BY at", (since.isoformat(),)).fetchall()
        return [dict(r) for r in rows]

    def history(self, person: str | None, since: datetime, limit: int = 60) -> list[dict]:
        """La conversation d'une personne (ou celle sans personne) et les messages de l'assistant au foyer, du plus
        ancien au plus récent ; les `limit` derniers."""
        talks = self._exec(
            "SELECT * FROM conversations WHERE person IS ? AND at >= ? ORDER BY at", (person, since.isoformat())
        ).fetchall()
        items = [
            {
                "kind": "talk",
                "at": r["at"],
                "text": r["text"],
                "answer": r["answer"],
                "voice": bool(r["voice"]),
                "done": json.loads(r["done"]) if r["done"] else [],
            }
            for r in talks
        ]
        items += [
            {"kind": "message", "at": m["at"], "title": m["title"], "text": m["text"]} for m in self.messages(since)
        ]
        items.sort(key=lambda i: i["at"])
        return items[-limit:] if limit > 0 else []

    # remarques de l'observateur (spec §12)
    def said(self, subject: str, at: datetime) -> None:
        self._exec(
            "INSERT INTO remarks (subject, said_at) VALUES (?, ?) ON CONFLICT(subject) DO UPDATE SET said_at = ?",
            (subject, at.isoformat(), at.isoformat()),
        )

    def refuse(self, subject: str, at: datetime) -> datetime:
        """Un « non » : une semaine de silence, puis le double à chaque refus suivant ; rend la fin du silence."""
        row = self._exec("SELECT refusals FROM remarks WHERE subject = ?", (subject,)).fetchone()
        refusals = (row["refusals"] if row else 0) + 1
        until = at + FIRST_SILENCE * (2 ** (refusals - 1))
        self._exec(
            "INSERT INTO remarks (subject, refusals, quiet_until) VALUES (?, ?, ?) "
            "ON CONFLICT(subject) DO UPDATE SET refusals = ?, quiet_until = ?",
            (subject, refusals, until.isoformat(), refusals, until.isoformat()),
        )
        return until

    def quiet(self, subject: str, at: datetime, repeat_after: timedelta = timedelta(hours=24)) -> bool:
        """Un sujet à taire : refusé et encore en silence, ou déjà dit depuis moins de `repeat_after`."""
        row = self._exec("SELECT * FROM remarks WHERE subject = ?", (subject,)).fetchone()
        if row is None:
            return False
        if row["quiet_until"] and datetime.fromisoformat(row["quiet_until"]) > at:
            return True
        return bool(row["said_at"]) and datetime.fromisoformat(row["said_at"]) + repeat_after > at

    # engagements (spec « préparer demain » §6)
    def offer(self, kind: str, question: str, offer: str, expires: datetime, at: datetime | None = None) -> int:
        """Une proposition du plan, en attente d'un « oui » ; `offer` est sa forme JSON (geste, heure, condition)."""
        cur = self._exec(
            "INSERT INTO engagements (kind, question, offer, state, offered_at, expires) VALUES (?, ?, ?, ?, ?, ?)",
            (kind, question, offer, OFFERED, (at or now_utc()).isoformat(), expires.isoformat()),
        )
        return int(cur.lastrowid or 0)

    def engagements(self, *states: str) -> list[dict]:
        marks = ",".join("?" * len(states))
        rows = self._exec(f"SELECT * FROM engagements WHERE state IN ({marks}) ORDER BY id", states).fetchall()
        return [dict(r) for r in rows]

    def engagement(self, engagement_id: int) -> dict | None:
        row = self._exec("SELECT * FROM engagements WHERE id = ?", (engagement_id,)).fetchone()
        return dict(row) if row else None

    def settle(
        self,
        engagement_id: int,
        state: str,
        person: str | None = None,
        outcome: str | None = None,
        armed_at: datetime | None = None,
        only_from: tuple[str, ...] = (),
    ) -> bool:
        """Change l'état d'un engagement (et retient qui a dit oui, ce qui s'est passé, depuis quand il est armé) ;
        `only_from` : seulement s'il est dans l'un de ces états."""
        sql = (
            "UPDATE engagements SET state = ?, person = COALESCE(?, person), outcome = COALESCE(?, outcome), "
            "armed_at = COALESCE(?, armed_at) WHERE id = ?"
        )
        args: list = [state, person, outcome, armed_at.isoformat() if armed_at else None, engagement_id]
        if only_from:
            sql += f" AND state IN ({','.join('?' * len(only_from))})"
            args += list(only_from)
        return self._exec(sql, args).rowcount > 0

    def disarm(self, engagement_id: int) -> None:
        self._exec("UPDATE engagements SET armed_at = NULL WHERE id = ?", (engagement_id,))

    def last_talk(self, person: str | None) -> str | None:
        row = self._exec(
            "SELECT at FROM conversations WHERE person IS ? ORDER BY at DESC LIMIT 1", (person,)
        ).fetchone()
        return row["at"] if row else None

    def last_said(self) -> str | None:
        row = self._exec(
            "SELECT subject FROM remarks WHERE said_at IS NOT NULL ORDER BY said_at DESC LIMIT 1"
        ).fetchone()
        return row["subject"] if row else None

    # les réglages par l'assistant (spec de l'assistant complet §5) : proposés, appliqués après un oui, annulables
    def propose_settings(
        self,
        person: str | None,
        revision: int,
        changes: list,
        undo: list,
        summary: list,
        at: datetime,
        undoes: int | None = None,
    ) -> int:
        cur = self._exec(
            "INSERT INTO settings_changes (person, at, revision, changes, undo, summary, state, undoes) VALUES (?, ?, ?, ?, ?, ?, 'PROPOSED', ?)",
            (
                person,
                at.isoformat(),
                revision,
                *(json.dumps(v, ensure_ascii=False) for v in (changes, undo, summary)),
                undoes,
            ),
        )
        return int(cur.lastrowid or 0)

    def settings_change(self, change_id: int) -> dict | None:
        return _setting(self._exec("SELECT * FROM settings_changes WHERE id = ?", (change_id,)).fetchone())

    def settings_applied(self, change_id: int, undo: list, at: datetime) -> None:
        self._exec(
            "UPDATE settings_changes SET state = 'APPLIED', undo = ?, applied_at = ? WHERE id = ?",
            (json.dumps(undo, ensure_ascii=False), at.isoformat(), change_id),
        )

    def last_applied_settings(self, person: str | None) -> dict | None:
        """Le dernier réglage appliqué pour cette personne et pas encore annulé."""
        return _setting(
            self._exec(
                "SELECT * FROM settings_changes WHERE state = 'APPLIED' AND undone_by IS NULL AND person IS ? ORDER BY id DESC LIMIT 1",
                (person,),
            ).fetchone()
        )

    def settings_refused(self, change_id: int) -> None:
        """Un « non » à la question : la proposition ne s'appliquera plus."""
        self._exec("UPDATE settings_changes SET state = 'REFUSED' WHERE id = ? AND state = 'PROPOSED'", (change_id,))

    def settings_undone_by(self, change_id: int, by: int) -> None:
        self._exec("UPDATE settings_changes SET undone_by = ? WHERE id = ?", (by, change_id))


def _setting(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    out = dict(row)
    for key in ("changes", "undo", "summary"):
        out[key] = json.loads(out[key])
    return out


def _words(text: str) -> list[str]:
    from .grammar import normalize

    return normalize(text).split()
