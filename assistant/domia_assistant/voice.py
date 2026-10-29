"""La voix (spec de l'écran §6) : la parole transcrite et la réponse dite sur la machine IA, rien ne sort de la maison.
La transcription par Whisper (`mlx-whisper`, le son décodé par `ffmpeg`), la réponse par la synthèse de macOS (`say`).
Un son n'est jamais gardé : un fichier temporaire, effacé dès qu'il est lu."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

LOG = logging.getLogger("assistant")

SUFFIXES = {
    "audio/mp4": ".m4a",
    "audio/x-m4a": ".m4a",
    "audio/aac": ".aac",
    "audio/webm": ".webm",
    "audio/ogg": ".ogg",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/mpeg": ".mp3",
}
SPEECH_MIME = "audio/mp4"
# Homebrew (Apple Silicon, puis Intel) : un LaunchAgent démarre avec un PATH réduit à /usr/bin:/bin:/usr/sbin:/sbin,
# et mlx-whisper appelle `ffmpeg` par son nom.
BREW_BINS = ("/opt/homebrew/bin", "/usr/local/bin")


def with_brew(path: str) -> str:
    """Le PATH, complété des dossiers de Homebrew qui lui manquent."""
    parts = [p for p in path.split(os.pathsep) if p]
    return os.pathsep.join(parts + [b for b in BREW_BINS if b not in parts])


class VoiceUnavailable(Exception):
    """Pas de transcription sur cette machine (mlx-whisper ou ffmpeg manquent) : l'écrit marche toujours."""


def kind(mime: str | None) -> str | None:
    """Le type de son accepté (sans ses paramètres : « audio/webm;codecs=opus » → « audio/webm »), ou None."""
    base = (mime or "").split(";")[0].strip().lower()
    return base if base in SUFFIXES else None


class Voice:
    def __init__(
        self,
        stt_model: str = "mlx-community/whisper-large-v3-turbo",
        language: str = "fr",
        say_voice: str | None = None,
    ):
        self.stt_model = stt_model
        self.language = language
        self.say_voice = say_voice
        self.lock = threading.Lock()  # un modèle en mémoire, une transcription à la fois
        os.environ["PATH"] = with_brew(os.environ.get("PATH", ""))

    def available(self) -> str | None:
        """None si la voix marche ; sinon ce qui manque."""
        try:
            import mlx_whisper  # noqa: F401
        except ImportError:
            return "mlx-whisper n'est pas installé"
        if shutil.which("ffmpeg") is None:
            return "ffmpeg n'est pas installé"
        return None

    def transcribe(self, audio: bytes, mime: str) -> str:
        missing = self.available()
        if missing:
            raise VoiceUnavailable(missing)
        import mlx_whisper

        with tempfile.TemporaryDirectory(prefix="domia-voix-") as folder:
            path = Path(folder) / ("parole" + SUFFIXES[kind(mime) or "audio/mp4"])
            path.write_bytes(audio)
            with self.lock:
                result = mlx_whisper.transcribe(str(path), path_or_hf_repo=self.stt_model, language=self.language)
        return " ".join(str(result.get("text") or "").split())

    def speak(self, text: str) -> bytes | None:
        """La réponse dite par `say`, en AAC (.m4a) ; None hors macOS ou si `say` échoue : l'écran montre le texte."""
        if not text.strip() or shutil.which("say") is None:
            return None
        with tempfile.TemporaryDirectory(prefix="domia-voix-") as folder:
            out = Path(folder) / "reponse.m4a"
            command = ["say", "-o", str(out), "--file-format=m4af", "--data-format=aac"]
            if self.say_voice:
                command += ["-v", self.say_voice]
            try:
                subprocess.run([*command, "--", text[:1000]], check=True, timeout=30, capture_output=True)
                return out.read_bytes()
            except (subprocess.SubprocessError, OSError) as e:
                LOG.warning("speak_failed error=%s", type(e).__name__)
                return None
