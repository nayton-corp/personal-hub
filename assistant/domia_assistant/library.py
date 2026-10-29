"""La bibliothèque des objets du ménage (spec §8) : `~/Domia/Bibliothèque/`, une fiche YAML par objet et ses documents à
côté, plus les documents du foyer (bail, assurances, décomptes). Les documents sont découpés en passages et indexés en
local (SQLite ; embeddings par le serveur de modèle s'il en sert, sinon par mots) ; une réponse cite sa source et sa
page. Les photos et PDF à classer attendent dans `à-trier/`."""

from __future__ import annotations

import email
import email.policy
import math
import re
import sqlite3
import struct
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import yaml

INBOX = "à-trier"
TEXT_EXT = {".txt", ".md"}
DOC_EXT = TEXT_EXT | {".pdf", ".eml"}
PHOTO_EXT = {".jpg", ".jpeg", ".png", ".heic"}
CARD_FIELDS = {
    "name",
    "room",
    "brand",
    "model",
    "serial",
    "bought_at",
    "shop",
    "price_chf",
    "warranty_until",
    "domia",
    "maintenance",
    "parts",
    "documents",
    "notes",
}
CHUNK_CHARS = 1200
EVERY = re.compile(r"^\s*(\d+)\s*(jour|jours|semaine|semaines|mois|an|ans|annee|annees)\s*$")

Embedder = Callable[[list[str]], list[list[float]]]


@dataclass(frozen=True)
class Passage:
    source: str
    page: int | None
    text: str
    score: float

    def cite(self) -> str:
        return f"{self.source}, p. {self.page}" if self.page else self.source


def every(text: str) -> timedelta | None:
    """« 1 mois », « 2 semaines », « 1 an » en durée ; None si illisible."""
    m = EVERY.match(str(text).lower().replace("é", "e"))
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2)
    days = {
        "jour": 1,
        "jours": 1,
        "semaine": 7,
        "semaines": 7,
        "mois": 30,
        "an": 365,
        "ans": 365,
        "annee": 365,
        "annees": 365,
    }[unit]
    return timedelta(days=n * days)


class Library:
    def __init__(self, folder: Path, database: Path | str, embed: Embedder | None = None):
        self.folder = folder
        self.embed = embed
        self.folder.mkdir(parents=True, exist_ok=True)
        (self.folder / INBOX).mkdir(exist_ok=True)
        if str(database) != ":memory:":
            Path(database).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(database), check_same_thread=False)
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS passages (source TEXT, page INTEGER, text TEXT, mtime REAL, vector BLOB)"
        )
        self.lock = threading.Lock()

    # fiches
    def cards(self) -> dict[str, dict]:
        out = {}
        for path in sorted(self.folder.glob("*.yaml")):
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            out[path.stem] = data
        return out

    def card(self, card_id: str) -> dict | None:
        path = self._card_path(card_id)
        return yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else None

    def save_card(self, card_id: str, fields: dict) -> dict:
        """Crée ou complète une fiche ; seuls les champs connus (§8.1) sont gardés."""
        unknown = set(fields) - CARD_FIELDS
        if unknown:
            raise ValueError(f"champs inconnus : {', '.join(sorted(unknown))}")
        card = self.card(card_id) or {}
        card.update({k: v for k, v in fields.items() if v is not None})
        self._card_path(card_id).write_text(yaml.safe_dump(card, allow_unicode=True, sort_keys=False), encoding="utf-8")
        return card

    def _card_path(self, card_id: str) -> Path:
        if not re.fullmatch(r"[\w\- ]{1,80}", card_id):
            raise ValueError("un id de fiche : lettres, chiffres, espaces, - et _")
        return self.folder / f"{card_id}.yaml"

    def maintenance_due(self, today: date) -> list[dict]:
        """Les tâches d'entretien des fiches dont l'échéance est passée (constat MAINTENANCE_DUE, spec §11)."""
        due = []
        for card_id, card in self.cards().items():
            for task in card.get("maintenance", []) or []:
                period = every(task.get("every", ""))
                last = task.get("last")
                if period is None or last is None:
                    continue
                last = last if isinstance(last, date) else date.fromisoformat(str(last))
                if last + period <= today:
                    due.append(
                        {
                            "card": card_id,
                            "name": card.get("name", card_id),
                            "what": task.get("what"),
                            "since": (last + period).isoformat(),
                        }
                    )
        return due

    def inbox(self) -> list[Path]:
        return sorted(p for p in (self.folder / INBOX).iterdir() if p.is_file() and not p.name.startswith("."))

    # documents
    def index(self) -> int:
        """(Ré)indexe les documents changés ; rend le nombre de passages écrits."""
        written = 0
        seen = set()
        for path in sorted(self.folder.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in DOC_EXT or INBOX in path.parts:
                continue
            source = str(path.relative_to(self.folder))
            seen.add(source)
            mtime = path.stat().st_mtime
            with self.lock:
                row = self.db.execute("SELECT mtime FROM passages WHERE source = ? LIMIT 1", (source,)).fetchone()
            if row and row[0] == mtime:
                continue
            chunks = [(page, c) for page, text in read_pages(path) for c in chunk(text)]
            vectors = self.embed([c for _, c in chunks]) if (self.embed and chunks) else [None] * len(chunks)
            with self.lock:
                self.db.execute("DELETE FROM passages WHERE source = ?", (source,))
                self.db.executemany(
                    "INSERT INTO passages VALUES (?, ?, ?, ?, ?)",
                    [(source, page, c, mtime, pack(v)) for (page, c), v in zip(chunks, vectors, strict=False)],
                )
                self.db.commit()
            written += len(chunks)
        with self.lock:
            for (source,) in self.db.execute("SELECT DISTINCT source FROM passages").fetchall():
                if source not in seen:
                    self.db.execute("DELETE FROM passages WHERE source = ?", (source,))
            self.db.commit()
        return written

    def search(self, question: str, k: int = 5) -> list[Passage]:
        with self.lock:
            rows = self.db.execute("SELECT source, page, text, vector FROM passages").fetchall()
        if not rows:
            return []
        if self.embed and all(r[3] for r in rows):
            q = self.embed([question])[0]
            # un code (E24, WM14N2B0CH) ne se ressemble pas par le sens : le passage qui le porte passe devant
            codes = {t for t in _terms(question) if any(c.isdigit() for c in t)}
            scored = [
                (cosine(q, unpack(r[3])) + (len(codes & set(_terms(r[2]))) / len(codes) if codes else 0.0), r)
                for r in rows
            ]
        else:
            terms = set(_terms(question))
            scored = [(lexical(terms, r[2]), r) for r in rows]
        scored = [s for s in scored if s[0] > 0]
        scored.sort(key=lambda s: -s[0])
        return [Passage(r[0], r[1], r[2], round(score, 3)) for score, r in scored[:k]]


def read_pages(path: Path) -> list[tuple[int | None, str]]:
    ext = path.suffix.lower()
    if ext in TEXT_EXT:
        return [(None, path.read_text(encoding="utf-8", errors="replace"))]
    if ext == ".eml":
        message = email.message_from_bytes(path.read_bytes(), policy=email.policy.default)
        body = message.get_body(preferencelist=("plain", "html"))
        text = body.get_content() if body else ""
        return [(None, f"{message.get('subject', '')}\n{message.get('from', '')}\n{message.get('date', '')}\n{text}")]
    if ext == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        return [(i + 1, page.extract_text() or "") for i, page in enumerate(reader.pages)]
    return []


def chunk(text: str, size: int = CHUNK_CHARS) -> list[str]:
    """Des passages d'environ `size` caractères, coupés entre paragraphes quand c'est possible."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    out, current = [], ""
    for p in paragraphs:
        while len(p) > size:
            if current:
                out.append(current)
                current = ""
            out.append(p[:size])
            p = p[size:]
        if len(current) + len(p) + 2 > size and current:
            out.append(current)
            current = p
        else:
            current = f"{current}\n\n{p}" if current else p
    if current:
        out.append(current)
    return out


def _terms(text: str) -> list[str]:
    from .grammar import normalize

    return [w for w in normalize(text).split() if len(w) > 2]


def lexical(terms: set[str], text: str) -> float:
    words = _terms(text)
    if not words or not terms:
        return 0.0
    hits = sum(1 for w in words if w in terms)
    return len(terms & set(words)) + hits / (len(words) + 10)


def pack(vector: list[float] | None) -> bytes | None:
    return None if vector is None else struct.pack(f"{len(vector)}f", *vector)


def unpack(blob: bytes) -> list[float]:
    return list(struct.unpack(f"{len(blob) // 4}f", blob))


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def today_local() -> date:
    return datetime.now().date()
