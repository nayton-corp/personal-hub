"""Texte d'un PDF VIAC par `pdftotext -layout` (poppler), comme les scripts du Mac.

Le PDF vient d'un tiers : il est lu par un processus séparé, sans shell, avec un délai, une
taille d'entrée et une mémoire plafonnés, et rien n'est écrit sur le disque (entrée et
sortie par les tubes). Les parseurs ne voient que le texte.
"""

from __future__ import annotations

import os
import resource
import shutil
import subprocess

from hub.domains.finance.sources.infra.viac import ViacError

MAGIC = b"%PDF-"
MAX_BYTES = 20 * 1024 * 1024
MAX_TEXT = 5 * 1024 * 1024
TIMEOUT_SECONDS = 30
MEMORY_BYTES = 512 * 1024 * 1024


def is_pdf(data: bytes) -> bool:
    return data[:1024].lstrip().startswith(MAGIC)


def _limits() -> None:  # pragma: no cover - exécuté dans le processus fils
    resource.setrlimit(resource.RLIMIT_AS, (MEMORY_BYTES, MEMORY_BYTES))
    resource.setrlimit(resource.RLIMIT_CPU, (TIMEOUT_SECONDS, TIMEOUT_SECONDS))
    resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))


def pdftotext(data: bytes) -> str:
    """Texte « mise en page » du PDF, pages séparées par un saut de page (\\f)."""
    if len(data) > MAX_BYTES:
        raise ViacError("viac.unreadable", "PDF trop volumineux")
    if not is_pdf(data):
        raise ViacError("viac.unreadable", "ce fichier n'est pas un PDF")
    binary = shutil.which("pdftotext")
    if binary is None:
        raise ViacError("viac.unreadable", "pdftotext absent (paquet poppler-utils)")
    try:
        done = subprocess.run(  # noqa: S603 - binaire résolu, arguments fixes
            [binary, "-layout", "-enc", "UTF-8", "-q", "-", "-"],
            input=data,
            capture_output=True,
            timeout=TIMEOUT_SECONDS,
            check=False,
            env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LANG": "C.UTF-8"},
            preexec_fn=_limits,  # limites posées avant exec, aucun thread
        )
    except subprocess.TimeoutExpired:
        raise ViacError("viac.unreadable", "lecture du PDF trop longue") from None
    if done.returncode != 0 or len(done.stdout) > MAX_TEXT:
        raise ViacError("viac.unreadable", "PDF illisible")
    return done.stdout.decode("utf-8", errors="replace")
