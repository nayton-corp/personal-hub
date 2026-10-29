"""Commandes `hub finance …` : celles de chaque sous-contexte, et celles du domaine entier
(vérifier le journal, reconstruire les index ou le registre, comparer deux bases, recalculer
les données dérivées). Les sorties sont des identifiants et des compteurs, jamais le contenu
d'une écriture.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Annotated

import typer
from sqlalchemy import text

from hub.core.context import HubContext
from hub.core.registry import Registry
from hub.domains.finance import compare, rebuild
from hub.domains.finance.classement.interface import cli as classement
from hub.domains.finance.port import Finance
from hub.domains.finance.registre.interface import cli as registre
from hub.domains.finance.registre.interface.terminal import out as _out
from hub.domains.finance.sources.interface import cli as sources
from hub.platform.db import begin_immediate, make_engine
from hub.platform.settings import Settings


def build_cli(domain: Finance, make: Callable[[Settings], Finance]) -> typer.Typer:
    """`make` crée une autre instance du domaine (la base reconstruite par `rebuild`)."""
    app = typer.Typer(no_args_is_help=True, help="Domaine Finance")
    accounts = typer.Typer(no_args_is_help=True, help="Comptes")
    categories = typer.Typer(no_args_is_help=True, help="Catégories")
    imports = typer.Typer(no_args_is_help=True, help="Imports")
    rules_app = typer.Typer(no_args_is_help=True, help="Règles de catégorisation")
    packs_app = typer.Typer(no_args_is_help=True, help="Packs de règles de départ")
    rules_app.add_typer(packs_app, name="packs")
    app.add_typer(rules_app, name="rules")
    app.add_typer(accounts, name="accounts")
    app.add_typer(categories, name="categories")
    app.add_typer(imports, name="imports")
    viac = typer.Typer(no_args_is_help=True, help="VIAC (pilier 3a)")
    app.add_typer(viac, name="viac")
    revolut_app = typer.Typer(no_args_is_help=True, help="Revolut (Enable Banking, CSV)")
    app.add_typer(revolut_app, name="revolut")
    ibkr_app = typer.Typer(no_args_is_help=True, help="IBKR (Flex Query)")
    app.add_typer(ibkr_app, name="ibkr")
    crypto_app = typer.Typer(no_args_is_help=True, help="Portefeuilles crypto (adresses)")
    app.add_typer(crypto_app, name="crypto")
    positions_app = typer.Typer(no_args_is_help=True, help="Positions saisies à la main")
    app.add_typer(positions_app, name="positions")
    engine = domain.engine()

    def ready() -> None:
        if not domain.is_current():
            typer.echo("finance.db n'est pas à jour : lancer `hub db upgrade`.", err=True)
            raise typer.Exit(2)

    @app.command("verify-ledger")
    def verify_ledger() -> None:
        """Recalcule la chaîne du journal et l'empreinte de chaque ligne ; 1 au moindre écart."""
        ready()
        result = domain.verify_ledger()
        _out(result.public())
        if not result.ok:
            raise typer.Exit(1)

    @app.command("rebuild-fts")
    def rebuild_fts() -> None:
        """Reconstruit les index plein texte (après une restauration)."""
        ready()
        with begin_immediate(engine) as conn:
            conn.execute(text("INSERT INTO entries_fts(entries_fts) VALUES('rebuild')"))
            conn.execute(text("INSERT INTO notes_fts(notes_fts) VALUES('rebuild')"))
        _out({"rebuilt": ["entries_fts", "notes_fts"]})

    @app.command("rebuild")
    def rebuild_cmd(
        out: Annotated[Path, typer.Option(help="dossier de la base reconstruite (vide)")],
    ) -> None:
        """Reconstruit le registre par rejeu dans `<out>/finance.db` (la base d'origine n'est
        pas touchée), puis le compare à l'origine. Compteurs seuls ; 1 au moindre écart."""
        ready()
        if (out / "finance.db").exists():
            typer.echo(f"{out / 'finance.db'} existe déjà", err=True)
            raise typer.Exit(1)
        paths = domain.settings.paths.model_copy(update={"data": out})
        target = make(domain.settings.model_copy(update={"paths": paths}))
        target.importer.pdf_text = domain.importer.pdf_text
        hub = HubContext.build(domain.settings, Registry([domain]))
        try:
            applied = rebuild.applied_proposals(engine, hub.core.engine)
        finally:
            hub.core.dispose()
        try:
            report = rebuild.rebuild(domain, target, applied)
            diff = compare.compare(engine, target.engine())
            check = target.verify_ledger()
        finally:
            target.engine().dispose()
        _out({**report.public(), "verify_ledger": check.ok, "compare": diff.public()})
        if not (report.ok and diff.ok and check.ok):
            raise typer.Exit(1)

    @app.command("compare")
    def compare_cmd(
        other: Annotated[
            Path, typer.Argument(exists=True, dir_okay=False, help="autre finance.db")
        ],
    ) -> None:
        """Compare le registre à une autre base (reconstruite ou restaurée) ; 1 au moindre écart."""
        ready()
        other_engine = make_engine(other)
        try:
            diff = compare.compare(engine, other_engine)
        finally:
            other_engine.dispose()
        _out(diff.public())
        if not diff.ok:
            raise typer.Exit(1)

    @app.command("derived")
    def derived_cmd() -> None:
        """Recalcule les instantanés, les virements appariés et les abonnements."""
        ready()
        refreshed = domain.refresh_snapshots(force=True)
        _out({"snapshots": refreshed.rows, **domain.refresh_derived()})

    registre.register(domain, ready, accounts=accounts, categories=categories)
    classement.register(domain, ready, rules_app=rules_app, packs_app=packs_app)
    sources.register(
        domain,
        ready,
        app=app,
        imports=imports,
        viac=viac,
        revolut_app=revolut_app,
        ibkr_app=ibkr_app,
        crypto_app=crypto_app,
        positions_app=positions_app,
    )
    return app
