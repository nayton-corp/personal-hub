"""Le texte d'un document, page par page : texte brut, Markdown, courriel (.eml) et PDF.

Le PDF vient souvent d'un tiers : `pdftotext` (poppler) le lit dans un processus séparé, sans
shell, avec un délai, une mémoire et une sortie plafonnés, entrée et sortie par les tubes. Un
format inconnu (une photo) n'a pas de texte : le document s'archive quand même.
"""

from __future__ import annotations

import email
import email.policy
import mimetypes
import os
import resource
import shutil
import subprocess

TEXT = frozenset({".txt", ".md"})
SUFFIXES = frozenset({*TEXT, ".eml", ".pdf", ".jpg", ".jpeg", ".png", ".heic"})
MAX_BYTES = 100 * 1024 * 1024  # une notice scannée dépasse souvent 50 Mo
MAX_TEXT = 5 * 1024 * 1024
TIMEOUT_SECONDS = 30
MEMORY_BYTES = 512 * 1024 * 1024

Pages = list[tuple[int | None, str]]


class TextError(ValueError):
    pass


def suffix(name: str) -> str:
    return "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""


def mime(name: str) -> str:
    if suffix(name) == ".md":
        return "text/markdown"
    if suffix(name) == ".eml":
        return "message/rfc822"
    return mimetypes.guess_type(name)[0] or "application/octet-stream"


def pages(name: str, data: bytes) -> Pages:
    """Le texte de chaque page (`None` : pas de pages) ; vide pour une image."""
    ext = suffix(name)
    if ext in TEXT:
        return [(None, data.decode("utf-8", errors="replace"))]
    if ext == ".eml":
        message = email.message_from_bytes(data, policy=email.policy.default)
        body = message.get_body(preferencelist=("plain", "html"))
        content = body.get_content() if body is not None else ""
        head = "\n".join(str(message.get(h, "")) for h in ("subject", "from", "date"))
        return [(None, f"{head}\n{content}")]
    if ext == ".pdf":
        found = pdftotext(data).split("\f")
        return [(i + 1, page) for i, page in enumerate(found) if page.strip()]
    return []


def _limits() -> None:  # pragma: no cover - exécuté dans le processus fils
    resource.setrlimit(resource.RLIMIT_AS, (MEMORY_BYTES, MEMORY_BYTES))
    resource.setrlimit(resource.RLIMIT_CPU, (TIMEOUT_SECONDS, TIMEOUT_SECONDS))
    resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))


def pdftotext(data: bytes) -> str:
    """Le texte du PDF, pages séparées par un saut de page (\\f)."""
    if len(data) > MAX_BYTES:
        raise TextError("PDF trop volumineux")
    if not data[:1024].lstrip().startswith(b"%PDF-"):
        raise TextError("ce fichier n'est pas un PDF")
    binary = shutil.which("pdftotext")
    if binary is None:  # pragma: no cover - poppler-utils est dans l'image
        raise TextError("pdftotext absent (paquet poppler-utils)")
    try:
        done = subprocess.run(  # noqa: S603 - binaire résolu, arguments fixes
            [binary, "-enc", "UTF-8", "-q", "-", "-"],
            input=data,
            capture_output=True,
            timeout=TIMEOUT_SECONDS,
            check=False,
            env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LANG": "C.UTF-8"},
            preexec_fn=_limits,  # limites posées avant exec, aucun thread
        )
    except subprocess.TimeoutExpired as exc:
        raise TextError("PDF trop long à lire") from exc
    if done.returncode != 0:
        raise TextError("PDF illisible")
    return done.stdout[:MAX_TEXT].decode("utf-8", errors="replace")
