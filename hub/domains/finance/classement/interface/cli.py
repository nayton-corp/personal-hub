"""Commandes `hub finance rules …` : lister les règles, reprendre celles de l'ancien script,
installer un pack, exporter ses règles, et les faire tourner sur ce qui n'a pas de catégorie.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Annotated

import typer

from hub.domains.finance.classement.app import legacy, packs, rules
from hub.domains.finance.registre.interface import terminal
from hub.domains.finance.registre.interface.terminal import out as _out
from hub.platform.db import begin_immediate


def register(
    host: terminal.Host,
    ready: Callable[[], None],
    *,
    rules_app: typer.Typer,
    packs_app: typer.Typer,
) -> None:
    engine = host.engine()

    @rules_app.command("list")
    def rules_list(
        all_: Annotated[bool, typer.Option("--all", help="avec les règles désactivées")] = False,
    ) -> None:
        ready()
        with engine.connect() as conn:
            typer.echo(f"version des règles : {rules.version(conn)}", err=True)
            for r in rules.list_rules(conn, active_only=not all_):
                state = "" if r.active else "  (désactivée)"
                typer.echo(
                    f"{r.priority:>5}  {r.id:<24} {r.field:<17} {r.direction:<6} "
                    f"{r.category_id:<20} « {r.pattern} »{state}"
                )

    @rules_app.command("import-legacy")
    def rules_import_legacy(
        path: Annotated[Path, typer.Argument(exists=True, dir_okay=False, help="bcf_rules.json")],
        run: Annotated[bool, typer.Option(help="catégoriser ensuite le registre")] = True,
    ) -> None:
        """Reprend le fichier de règles de `bcf_aggregate.py` (sur le Mac) ; compteurs seuls."""
        ready()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            with begin_immediate(engine) as conn:
                report = legacy.import_rules(conn, data, run=run)
        except (json.JSONDecodeError, legacy.LegacyError, rules.RuleError) as exc:
            typer.echo(f"fichier refusé : {exc}", err=True)
            raise typer.Exit(1) from exc
        _out(report.public())

    @packs_app.command("list")
    def packs_list() -> None:
        """Packs livrés avec le hub, et version installée de chacun."""
        ready()
        with engine.connect() as conn:
            done = packs.installed(conn)
        for p in packs.available().values():
            have = done.get(p.name)
            state = f"installé v{have}" if have else "non installé"
            typer.echo(f"{p.name:<8} v{p.version}  {state:<16} {p.label} : {p.description}")

    @packs_app.command("install")
    def packs_install(
        names: Annotated[list[str], typer.Argument(help="ex. base ch, ou un fichier .yaml")],
        dry_run: Annotated[
            bool, typer.Option("--dry-run", help="compter sans rien changer")
        ] = False,
    ) -> None:
        """Installe ou met à jour des packs ; une règle de même forme déjà présente n'est pas
        doublée, une règle du pack désactivée par toi le reste."""
        ready()
        found = packs.available()
        try:
            chosen = [
                packs.parse(Path(n).read_text(encoding="utf-8"))
                if n.endswith(".yaml")
                else found[n]
                for n in names
            ]
        except KeyError as exc:
            typer.echo(f"pack inconnu : {exc.args[0]} ({', '.join(found)})", err=True)
            raise typer.Exit(2) from None
        except (OSError, packs.PackError) as exc:
            typer.echo(f"pack refusé : {exc}", err=True)
            raise typer.Exit(1) from None
        with begin_immediate(engine) as conn:
            reports = [packs.install(conn, p, dry_run=dry_run).public() for p in chosen]
        _out({"packs": reports})

    @rules_app.command("export")
    def rules_export(
        path: Annotated[Path, typer.Argument(dir_okay=False, help="fichier .yaml à écrire")],
        name: Annotated[str, typer.Option(help="nom du pack exporté")] = "perso",
        origin: Annotated[
            list[str] | None, typer.Option(help="seed, legacy, user, pack-ch… (toutes sinon)")
        ] = None,
    ) -> None:
        """Écrit les règles actives (hors système) au format d'un pack, à réinstaller ailleurs
        avec `rules packs install fichier.yaml`. Contient tes mots-clés : à garder hors du dépôt."""
        ready()
        try:
            with engine.connect() as conn:
                pack = packs.export(conn, name, origins=origin or ())
        except packs.PackError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(2) from None
        path.write_text(packs.dump(pack), encoding="utf-8")
        _out({"rules": len(pack.specs()), "categories": len(pack.categories)})

    @rules_app.command("run")
    def rules_run() -> None:
        """Catégorise selon les règles actives ce qu'elles ont le droit de toucher (sans
        catégorie, ou catégorisé par une règle) ; une décision humaine n'est jamais remplacée."""
        ready()
        with begin_immediate(engine) as conn:
            changed = rules.run(conn)
        _out({"categorized": changed})
