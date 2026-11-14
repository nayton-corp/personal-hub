"""Commandes de fond de `hub` : nuit, contrôle, sauvegarde, restauration, planificateur.

Sorties de `hub.cli` (plafond de 400 lignes). Le planificateur les lance depuis la crontab ; un
code de sortie non nul y devient une alerte ntfy (`cli_ops.job_failed`).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from contextlib import nullcontext
from pathlib import Path
from typing import Annotated

import typer

from hub import cli_ops
from hub.core import proposal_reconcile, tasks
from hub.core.context import HubContext
from hub.core.notify import Message
from hub.platform import logging as hub_logging
from hub.platform.cron import REPORTED
from hub.platform.settings import get_settings

Ctx = Callable[[], HubContext]


def register(app: typer.Typer, ctx: Ctx, ready: Ctx) -> None:
    @app.command()
    def nightly() -> None:
        """Expiration des propositions, purges, réconciliation, tâches de nuit des domaines."""
        from hub.core.maintenance import nightly as run

        typer.echo(json.dumps(run(ready())))

    @app.command()
    def reconcile() -> None:
        """Recale les statuts des propositions sur `applied_proposals` (après une restauration)."""
        report = proposal_reconcile.reconcile(ready())
        typer.echo(json.dumps({"applied": report.marked_applied, "released": report.released}))

    @app.command()
    def verify(
        notify: Annotated[
            bool, typer.Option("--notify", help="Alerte ntfy si l'intégrité est en cause.")
        ] = False,
    ) -> None:
        """Intégrité de chaque base et de chaque domaine : code de sortie 1 au moindre écart.
        Les avertissements (un écart entre deux calculs) sont rendus sans faire échouer : ils
        n'empêchent pas une mise à jour, le contrôle de santé les signale."""
        from hub.core.maintenance import verify as run

        hub = ctx()
        with tasks.recorded(hub.core.engine, "hub.verify") as note:
            report = run(hub)
            typer.echo(json.dumps(report.public(), ensure_ascii=False))
            note.text = "intact" if report.ok else "en écart : " + ", ".join(report.failed)
            if not report.ok:
                _verify_failed(hub, report.failed, notify)

    def _verify_failed(hub: HubContext, failed: list[str], notify: bool) -> None:
        if notify and hub.notifier.send(
            Message(
                "Contrôle d'intégrité en échec",
                "En cause : " + ", ".join(failed)[:300] + ". Aucune donnée n'est modifiée ; "
                "regarder avant la prochaine mise à jour.",
                priority="urgent",
                tags="rotating_light",
            )
        ):
            raise typer.Exit(REPORTED)  # déjà signalé, avec le détail : le planificateur se tait
        raise typer.Exit(1)

    @app.command()
    def backup(
        dest: Annotated[
            Path | None, typer.Option(help="Dossier cible (défaut : paths.backup)")
        ] = None,
        stamp: Annotated[
            str | None, typer.Option(help="Suffixe des fichiers (défaut : date)")
        ] = None,
        restic: Annotated[bool, typer.Option(help="Puis restic vers chaque dépôt.")] = False,
    ) -> None:
        """Copie `.backup` cohérente de chaque base, vérifiée par `integrity_check`."""
        from hub.core.maintenance import backup_all, prune_local_copies, restic_backup

        hub = ctx()
        target = dest or hub.settings.paths.backup
        with tasks.recorded(hub.core.engine, "hub.backup") if restic else nullcontext() as note:
            files = backup_all(hub, target, stamp)
            out: dict[str, object] = {"files": [f.name for f in files]}
            if restic:
                out["pruned"] = prune_local_copies(target, hub.settings.backup.keep_local_days)
                out["restic"] = len(restic_backup(hub))
            if note is not None:
                note.text = f"{len(files)} bases copiées"
        typer.echo(json.dumps(out))

    @app.command("backup-check")
    def backup_check() -> None:
        """Essai de restauration : chaque dépôt restic est contrôlé, puis les dernières copies
        des bases en sont ressorties et comparées aux originaux. Code 1 au moindre écart."""
        from hub.core.maintenance import restic_check

        hub = ctx()
        with tasks.recorded(hub.core.engine, "hub.backup_check") as note:
            try:
                typer.echo(json.dumps(restic_check(hub)))
            except RuntimeError as exc:
                typer.echo(str(exc), err=True)
                note.text = "copies en écart"
                raise typer.Exit(1) from exc
            note.text = "copies relues"

    @app.command()
    def restore(
        stamp: Annotated[str, typer.Argument(help="Suffixe des copies, ex. predeploy-v0.2.0")],
        source: Annotated[Path | None, typer.Option(help="Dossier des copies")] = None,
    ) -> None:
        """Remet les bases depuis une copie de `hub backup` (services arrêtés), puis réconcilie."""
        from hub.core.maintenance import restore as run

        try:
            restored = run(ctx(), stamp, source)
        except (FileNotFoundError, RuntimeError) as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc
        typer.echo(json.dumps({"restored": restored}))

    @app.command()
    def scheduler(crontab: Path, state: Path | None = None) -> None:
        """Exécute la crontab du dépôt (conteneur `scheduler`) ; `state` : dernière minute
        servie. Un job sorti en erreur donne une alerte ntfy."""
        from hub.platform.cron import run_forever

        hub_logging.configure(get_settings().log_level)
        last = state or get_settings().paths.data / "scheduler.last"
        hub = ctx()
        run_forever(
            crontab,
            state=last,
            on_failure=cli_ops.job_failed,
            requested=lambda: tasks.take_requested(hub.core.engine, hub),
        )

    task_app = typer.Typer(no_args_is_help=True, help="Tâches planifiées, relancées à la main")
    app.add_typer(task_app, name="task")

    @task_app.command("list")
    def task_list() -> None:
        """Chaque tâche : horaire, demande en attente, dernier passage."""
        hub = ready()
        with hub.core.engine.connect() as conn:
            typer.echo(json.dumps(tasks.status(conn, hub), ensure_ascii=False))

    @task_app.command("run")
    def task_run(name: Annotated[str, typer.Argument(help="ex. finance.strategies")]) -> None:
        """Lance tout de suite un morceau de la nuit (ce que fait le planificateur sur demande
        de l'app). L'entretien a ses propres commandes : `hub backup --restic`…"""
        from hub.core.maintenance import housekeeping

        hub = ready()
        if name == tasks.HOUSEKEEPING:
            with tasks.recorded(hub.core.engine, name) as note:
                note.text = "fait"
                typer.echo(json.dumps(housekeeping(hub)))
            return
        task = tasks.find(hub, name)
        if task.run is None:
            typer.echo(f"{name} : lancer « {' '.join(task.command) or 'depuis l app'} »", err=True)
            raise typer.Exit(2)
        typer.echo(json.dumps({"task": name, "said": tasks.run_domain_task(hub, task)}))
