"""Les réglages de l'assistant (spec §6) : `config.yaml` à côté du service, le jeton dans `.env` ou l'environnement,
jamais dans le dépôt. Changer de modèle est une ligne."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .hub import HubSettings
from .hub import settings as hub_settings

HOME = Path.home() / "Domia"


@dataclass(frozen=True)
class Settings:
    domia_url: str
    domia_token: str
    # le mot de passe de la configuration (htpasswd de Nginx) : sans lui, l'assistant propose un réglage mais ne
    # l'écrit pas derrière Nginx (spec de l'assistant complet §5, décision de Client 0 du 2026-10-25)
    config_user: str = "client0"
    config_password: str | None = field(default=None, repr=False)
    model_url: str = "http://127.0.0.1:11434/v1"  # Ollama ; LM Studio : http://127.0.0.1:1234/v1
    model: str = "mistral-small3.2:24b"
    embedding_model: str | None = "bge-m3"
    vision_model: str | None = None
    # combien de temps Ollama garde le modèle chargé après une question (son défaut : 5 min, puis 40 s de rechargement) ;
    # envoyé à chaque appel, donc vrai aussi après un redémarrage du Mac. None : le défaut du serveur
    keep_alive: str | None = "24h"
    # un modèle qui réfléchit avant de répondre (gpt-oss) : low, medium ou high ; sa réflexion compte dans MAX_TOKENS
    reasoning: str | None = None
    listen_host: str = "0.0.0.0"
    listen_port: int = 8770
    # qui peut appeler POST /talk : le Pi (Domia relaie) et la machine elle-même
    allow_from: tuple[str, ...] = ("127.0.0.1",)
    home: Path = HOME
    eventkit_url: str | None = "http://127.0.0.1:8771"
    web_search_url: str | None = None  # une instance SearXNG locale (format=json) ; absente : pas de recherche web
    brief_at: str | None = "21:00"  # None : pas de brief du soir (décision 7)
    timezone: str = "Europe/Zurich"
    max_steps: int = 6
    # le modèle en deux temps (spec de l'assistant complet §16.12) : classer la demande, puis ne montrer que les outils
    # de ce type ; à n'allumer qu'avec OLLAMA_NUM_PARALLEL (un cache par type), sinon chaque type recalcule ses outils
    route: bool = False
    # changer un réglage par l'assistant (spec §16.15) : éteint tant que le modèle ne choisit pas le bon champ ; il lit
    # les réglages et dit où les changer
    settings_write: bool = False
    # la voix (spec de l'écran §6) : Whisper sur la machine, la réponse dite par `say` ; None : la voix de macOS par défaut
    voice: bool = True
    stt_model: str = "mlx-community/whisper-large-v3-turbo"
    say_voice: str | None = None
    hub: HubSettings | None = None  # les outils du hub (domia_assistant.hub) ; absent : la maison seule
    database_file: str = (
        "assistant.sqlite"  # le banc a la sienne : ses conversations ne vont pas dans la mémoire du foyer
    )

    @property
    def library_dir(self) -> Path:
        return self.home / "Bibliothèque"

    @property
    def database(self) -> Path:
        return self.home / self.database_file


def read_env(path: Path) -> dict[str, str]:
    """Un `.env` simple : NOM=valeur par ligne, # pour les commentaires."""
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        out[name.strip()] = value.strip().strip('"').strip("'")
    return out


def load(path: Path, env: dict[str, str] | None = None) -> Settings:
    env = dict(os.environ if env is None else env)
    env = {**read_env(path.parent / ".env"), **env}
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
    raw = raw or {}
    token = env.get("DOMIA_ASSISTANT_TOKEN", "").strip()
    if not token:
        raise SystemExit("assistant : DOMIA_ASSISTANT_TOKEN manque (dans .env ou l'environnement)")
    domia = raw.get("domia", {}) or {}
    model = raw.get("model", {}) or {}
    listen = raw.get("listen", {}) or {}
    known = {f for f in Settings.__dataclass_fields__}
    extra = {k: v for k, v in (raw.get("assistant", {}) or {}).items() if k in known}
    if "home" in extra:
        extra["home"] = Path(os.path.expanduser(extra["home"]))
    return Settings(
        domia_url=str(domia.get("url", "http://192.168.0.63:3000")).rstrip("/"),
        domia_token=token,
        config_user=env.get("DOMIA_CONFIG_USER", "client0").strip() or "client0",
        config_password=env.get("DOMIA_CONFIG_PASSWORD", "").strip() or None,
        model_url=str(model.get("url", Settings.model_url)).rstrip("/"),
        model=str(model.get("name", Settings.model)),
        embedding_model=model.get("embeddings", Settings.embedding_model),
        vision_model=model.get("vision"),
        keep_alive=model.get("keep_alive", Settings.keep_alive),
        reasoning=model.get("reasoning"),
        listen_host=str(listen.get("host", Settings.listen_host)),
        listen_port=int(listen.get("port", Settings.listen_port)),
        allow_from=tuple(listen.get("allow_from", Settings.allow_from)),
        hub=hub_settings(raw.get("hub"), env),
        **extra,
    )
