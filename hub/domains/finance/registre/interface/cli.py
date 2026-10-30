"""Commandes `hub finance accounts …` et `hub finance categories …` : créer un compte ou une
catégorie passe par le Double Sas (la commande crée la proposition et la valide depuis le
terminal), puis les lister, ou ouvrir le registre d'un compte.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

import typer

from hub.domains.finance.registre.app import catalog, opening
from hub.domains.finance.registre.interface import terminal
from hub.domains.finance.registre.interface.terminal import out as _out
from hub.domains.finance.registre.interface.terminal import propose_and_accept
from hub.domains.finance.registre.model import errors
from hub.kernel.money import Money, base_currency
from hub.kernel.text import mask_iban
from hub.platform.db import begin_immediate


def register(
    host: terminal.Host,
    ready: Callable[[], None],
    *,
    accounts: typer.Typer,
    categories: typer.Typer,
) -> None:
    engine = host.engine()

    @accounts.command("add")
    def accounts_add(
        name: Annotated[str, typer.Argument(help="ex. « BCF compte privé »")],
        iban: Annotated[str | None, typer.Option(help="IBAN (comptes bancaires)")] = None,
        external_ref: Annotated[str | None, typer.Option(help="clé d'un compte sans IBAN")] = None,
        institution: Annotated[str, typer.Option()] = "BCF",
        kind: Annotated[str, typer.Option(help="cash, securities, pension, crypto")] = "cash",
        currency: Annotated[str | None, typer.Option(help="devise de base par défaut")] = None,
        liquid: Annotated[bool, typer.Option(help="compte dans les liquidités")] = False,
        budget: Annotated[bool, typer.Option(help="compte suivi par le budget")] = False,
    ) -> None:
        """Crée un compte par une proposition `create_account` validée depuis le terminal ; les
        relevés en attente sur cet IBAN sont relancés."""
        ready()
        result = propose_and_accept(
            host,
            "create_account",
            {
                "institution": institution,
                "name": name,
                "kind": kind,
                "currency": currency or base_currency(),
                "iban": iban,
                "external_ref": external_ref,
                "liquid": liquid,
                "budget_account": budget,
            },
        )
        _out(
            {"id": result["account_id"], "iban": result["iban"], "proposal": result["proposal_id"]}
        )

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
                opening.open_account(
                    conn, a.id, on, Money.from_decimal(amount, a.currency).minor, a.currency
                )
        except (catalog.CatalogError, errors.ImportRefused, ValueError) as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc
        _out({"opened": account_id})

    @categories.command("add")
    def categories_add(
        id: Annotated[str, typer.Argument(help="slug : alimentation, voyages…")],
        name: str,
        group: Annotated[str, typer.Option(help="fixed, variable, savings, income, transfer")],
    ) -> None:
        """Crée une catégorie par une proposition `create_category` validée depuis le terminal."""
        ready()
        result = propose_and_accept(host, "create_category", {"id": id, "name": name, "grp": group})
        _out({"id": id, "proposal": result["proposal_id"]})

    @categories.command("list")
    def categories_list() -> None:
        ready()
        with engine.connect() as conn:
            for c in catalog.list_categories(conn):
                typer.echo(f"{c.id:<20} {c.grp:<9} {c.name}{'' if c.active else ' (inactive)'}")
