"""Commandes `hub ops …` (chantier S7) : ce que les scripts d'exploitation lisent au lieu d'une
liste de bases en dur."""

from __future__ import annotations

import json
from collections.abc import Callable

import typer

from hub.core import ops
from hub.core.context import HubContext
from hub.core.notify import Message, Notifier
from hub.platform.settings import get_settings


def job_failed(command: tuple[str, ...], code: int) -> None:
    """Alerte du planificateur : un job de la crontab est sorti en erreur (audit du 10/11, O1).
    Le nom de la commande et son code, rien de ce qu'elle a écrit."""
    name = " ".join(command[:3])[:80]
    Notifier(get_settings()).send(
        Message(
            "Tâche planifiée en échec",
            f"{name} : code de sortie {code}. Détail dans les journaux du conteneur scheduler.",
            priority="high",
            tags="warning",
        )
    )


def build(ctx: Callable[[], HubContext]) -> typer.Typer:
    app = typer.Typer(no_args_is_help=True, help="Exploitation : bases et réplication")

    @app.command("databases")
    def databases() -> None:
        """Une base par ligne : core, puis chaque domaine monté (HUB_DOMAINS)."""
        for name in ops.database_names(ctx()):
            typer.echo(name)

    @app.command("litestream")
    def litestream() -> None:
        """La configuration Litestream de ces bases, sur la sortie standard."""
        typer.echo(ops.litestream_config(ctx()), nl=False)

    @app.command("notify")
    def notify(
        title: str,
        body: str,
        urgent: bool = typer.Option(False, "--urgent", help="priorité haute (un échec)"),
    ) -> None:
        """Une notification ntfy depuis un script d'exploitation (mise à jour du Pi). Un texte
        générique : jamais un montant. Sans sujet ntfy, rien n'est envoyé (code 0)."""
        Notifier(get_settings()).send(
            Message(title, body, priority="high" if urgent else "default", tags="package")
        )

    @app.command("health")
    def health() -> None:
        """Disques, réplique, sauvegardes, avertissements des domaines : alerte ce qui cloche,
        puis envoie le signal de vie si tout va bien. Code 0 : l'alerte est déjà partie."""
        from hub.core import health as checks

        typer.echo(json.dumps(checks.run(ctx()), ensure_ascii=False))

    return app
