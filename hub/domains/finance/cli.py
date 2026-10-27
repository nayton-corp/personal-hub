"""Commandes `hub finance …` : registre, comptes et catégories, imports, reprise d'historique.

Les sorties sont des identifiants et des compteurs, jamais le contenu d'une écriture.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer
from sqlalchemy import text

from hub.core.db import begin_immediate
from hub.core.money import Money
from hub.core.text import mask_iban
from hub.domains.finance import catalog, importer

if TYPE_CHECKING:
    from hub.domains.finance.domain import FinanceDomain


def _out(value: object) -> None:
    typer.echo(json.dumps(value, ensure_ascii=False))


def build_cli(domain: FinanceDomain) -> typer.Typer:
    app = typer.Typer(no_args_is_help=True, help="Domaine Finance")
    accounts = typer.Typer(no_args_is_help=True, help="Comptes")
    categories = typer.Typer(no_args_is_help=True, help="Catégories")
    imports = typer.Typer(no_args_is_help=True, help="Imports")
    app.add_typer(accounts, name="accounts")
    app.add_typer(categories, name="categories")
    app.add_typer(imports, name="imports")
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

    @accounts.command("add")
    def accounts_add(
        name: Annotated[str, typer.Argument(help="ex. « BCF compte privé »")],
        iban: Annotated[str | None, typer.Option(help="IBAN (comptes bancaires)")] = None,
        external_ref: Annotated[str | None, typer.Option(help="clé d'un compte sans IBAN")] = None,
        institution: Annotated[str, typer.Option()] = "BCF",
        kind: Annotated[str, typer.Option(help="cash, securities, pension, crypto")] = "cash",
        currency: Annotated[str, typer.Option()] = "CHF",
        liquid: Annotated[bool, typer.Option(help="compte dans les liquidités")] = False,
        budget: Annotated[bool, typer.Option(help="compte suivi par le budget")] = False,
    ) -> None:
        """Crée un compte (écriture directe tant que le Double Sas n'existe pas)."""
        ready()
        try:
            with begin_immediate(engine) as conn:
                a = catalog.add_account(
                    conn,
                    institution=institution,
                    name=name,
                    kind=kind,
                    currency=currency,
                    iban=iban,
                    external_ref=external_ref,
                    liquid=liquid,
                    budget_account=budget,
                )
        except catalog.CatalogError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc
        _out({"id": a.id, "iban": mask_iban(a.iban)})
        retried = domain.importer.retry_needs_review(quiet=True)
        if retried:
            _out({"retried": len(retried), "applied": sum(s.status == "applied" for s in retried)})

    @accounts.command("list")
    def accounts_list() -> None:
        ready()
        with engine.connect() as conn:
            for a in catalog.list_accounts(conn):
                flags = ",".join(
                    f for f, on in (("liquide", a.liquid), ("budget", a.budget_account)) if on
                )
                typer.echo(
                    f"{a.id}  {a.institution:<6} {a.kind:<10} {a.currency}  "
                    f"{mask_iban(a.iban) or a.external_ref or '':<10} {a.name}  {flags}"
                )

    @accounts.command("open")
    def accounts_open(
        account_id: str,
        on: Annotated[str, typer.Option(help="date de l'écriture d'ouverture, AAAA-MM-JJ")],
        amount: Annotated[str, typer.Option(help="solde d'ouverture, ex. 1234.50")],
    ) -> None:
        """Solde d'ouverture explicite d'un compte vide (la reprise d'historique le fait seule)."""
        ready()
        try:
            with begin_immediate(engine) as conn:
                a = catalog.get_account(conn, account_id)
                importer.open_account(
                    conn, a.id, on, Money.from_decimal(amount, a.currency).minor, a.currency
                )
        except (catalog.CatalogError, importer.ImportRefused, ValueError) as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc
        _out({"opened": account_id})

    @categories.command("add")
    def categories_add(
        id: Annotated[str, typer.Argument(help="slug : alimentation, voyages…")],
        name: str,
        group: Annotated[str, typer.Option(help="fixed, variable, savings, income, transfer")],
    ) -> None:
        ready()
        try:
            with begin_immediate(engine) as conn:
                catalog.add_category(conn, id=id, name=name, grp=group)
        except catalog.CatalogError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc
        _out({"id": id})

    @categories.command("list")
    def categories_list() -> None:
        ready()
        with engine.connect() as conn:
            for c in catalog.list_categories(conn):
                typer.echo(f"{c.id:<20} {c.grp:<9} {c.name}{'' if c.active else ' (inactive)'}")

    @app.command("watch-inbox")
    def watch_inbox(
        poll: Annotated[int, typer.Option(min=1, help="secondes entre deux passages")] = 30,
        once: Annotated[bool, typer.Option(help="un seul passage")] = False,
    ) -> None:
        """Surveille `inbox/` (xml et zip) ; chaque passage traite tout ce qui est prêt."""
        ready()
        while True:
            report = domain.importer.process_inbox()
            if report.files or once:
                _out(report.counters())
            if once:
                return
            time.sleep(poll)

    @app.command("import-history")
    def import_history(
        folder: Annotated[Path, typer.Argument(exists=True, file_okay=False)],
    ) -> None:
        """Reprise d'historique : trie, vérifie la continuité, ouvre, applique. Compteurs seuls."""
        ready()
        try:
            report = importer.import_history(domain.importer, folder)
        except importer.ImportRefused as exc:
            typer.echo(exc.detail, err=True)
            raise typer.Exit(1) from exc
        _out(report.public())
        if not report.ok:
            raise typer.Exit(1)

    @imports.command("list")
    def imports_list(
        status: Annotated[str | None, typer.Option(help="applied, needs_review…")] = None,
    ) -> None:
        ready()
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT id, received_at, status, stats_json FROM imports "
                    "WHERE :s IS NULL OR status = :s ORDER BY received_at"
                ),
                {"s": status},
            )
            for r in rows:
                stats = json.loads(r[3])
                reasons = ",".join(stats.get("reasons", []))
                typer.echo(
                    f"{r[0]}  {r[1][:16]}  {r[2]:<12} nouveaux={stats.get('new', 0)} "
                    f"doublons={stats.get('duplicates', 0)} motifs={reasons}"
                )

    @imports.command("retry")
    def imports_retry(ids: Annotated[list[str] | None, typer.Argument()] = None) -> None:
        """Rejoue les relevés en attente depuis l'archive chiffrée."""
        ready()
        try:
            outcomes = domain.importer.retry_needs_review(ids or None)
        except importer.ImportRefused as exc:
            typer.echo(exc.detail, err=True)
            raise typer.Exit(1) from exc
        _out(
            {
                "retried": len(outcomes),
                "applied": sum(o.status == "applied" for o in outcomes),
                "still_needs_review": sum(o.status == "needs_review" for o in outcomes),
            }
        )

    return app
