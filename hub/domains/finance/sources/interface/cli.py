"""Commandes des sources : surveiller `inbox/`, reprendre un historique, déclarer les comptes VIAC,
Revolut, IBKR, crypto ou saisis à la main, et suivre, rejouer ou relancer les imports. Les
sorties sont des identifiants et des compteurs, jamais le contenu d'une écriture.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Protocol

import typer
from sqlalchemy import text

from hub.domains.finance.registre.app import catalog
from hub.domains.finance.registre.interface import terminal
from hub.domains.finance.registre.interface.terminal import out as _out
from hub.domains.finance.registre.interface.terminal import propose_and_accept
from hub.domains.finance.registre.model import errors
from hub.domains.finance.sources.app import history, revolut_accounts
from hub.domains.finance.sources.app import viac as viac_apply
from hub.domains.finance.sources.app.importer import ImportService
from hub.domains.finance.sources.infra import ibkr_flex
from hub.domains.finance.sources.infra import viac as viac_patterns
from hub.kernel.money import base_currency


class Host(terminal.Host, Protocol):
    importer: ImportService


def register(
    host: Host,
    ready: Callable[[], None],
    *,
    app: typer.Typer,
    imports: typer.Typer,
    viac: typer.Typer,
    revolut_app: typer.Typer,
    ibkr_app: typer.Typer,
    crypto_app: typer.Typer,
    positions_app: typer.Typer,
) -> None:
    engine = host.engine()

    @app.command("watch-inbox")
    def watch_inbox(
        poll: Annotated[int, typer.Option(min=1, help="secondes entre deux passages")] = 30,
        once: Annotated[bool, typer.Option(help="un seul passage")] = False,
    ) -> None:
        """Surveille `inbox/` (xml, zip et PDF VIAC) ; traite tout ce qui est prêt."""
        ready()
        while True:
            report = host.importer.process_inbox()
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
            report = history.import_history(host.importer, folder)
        except errors.ImportRefused as exc:
            typer.echo(exc.detail, err=True)
            raise typer.Exit(1) from exc
        _out(report.public())
        if not report.ok:
            raise typer.Exit(1)

    @viac.command("add-portfolio")
    def viac_add_portfolio(
        number: Annotated[str, typer.Argument(help="n° de portefeuille, ex. 3.123.456.789.01")],
        name: Annotated[str, typer.Option(help="ex. « VIAC 1 »")],
    ) -> None:
        """Crée les deux comptes d'un portefeuille : liquidités 3a et titres (deux propositions
        `create_account` validées depuis le terminal)."""
        ready()
        if not re.fullmatch(viac_patterns.PORTFOLIO, number):
            typer.echo("numéro attendu : 3.123.456.789.01", err=True)
            raise typer.Exit(1)
        out = {}
        for side, ref, label in (
            ("cash", viac_apply.cash_ref(number), "liquidités"),
            ("titres", viac_apply.titles_ref(number), "titres"),
        ):
            with engine.connect() as conn:
                found = catalog.account_by_ref(conn, ref)
            if found is not None:
                out[side] = found.id
                continue
            result = propose_and_accept(
                host,
                "create_account",
                {
                    "institution": "VIAC",
                    "name": f"{name} {label}",
                    "kind": "pension",
                    "currency": "CHF",
                    "external_ref": ref,
                },
            )
            out[side] = str(result["account_id"])
        _out(out)

    @viac.command("import-history")
    def viac_import_history(
        folder: Annotated[Path, typer.Argument(exists=True, file_okay=False)],
    ) -> None:
        """Reprise des PDF VIAC (avis et rapports, sous-dossiers compris) : ouvre les comptes à
        zéro la veille du plus ancien document, puis applique tout par date. Compteurs seuls."""
        ready()
        report = history.import_viac_history(host.importer, folder)
        _out(report.public())
        if not report.ok:
            raise typer.Exit(1)

    @revolut_app.command("pending")
    def revolut_pending() -> None:
        """Comptes Revolut vus dans des fichiers en attente : clé, nombre d'écritures, période,
        motifs. Aucun montant."""
        ready()
        out = []
        for ref, items in sorted(revolut_accounts.revolut_pending(host.importer).items()):
            dates = [e.booking_date for _, st in items for e in st.entries]
            with engine.connect() as conn:
                known = catalog.account_by_ref(conn, ref) is not None
            out.append(
                {
                    "ref": ref,
                    "account_exists": known,
                    "imports": len({i for i, _ in items}),
                    "entries": sum(len(st.entries) for _, st in items),
                    "from": min(dates, default=None),
                    "to": max(dates, default=None),
                    "can_open": any(st.derived_opening for _, st in items),
                }
            )
        _out(out)

    @revolut_app.command("add-account")
    def revolut_add_account(
        ref: Annotated[str, typer.Argument(help="clé vue dans `pending`, ex. revolut:CHF")],
        name: Annotated[str, typer.Option(help="ex. « Revolut CHF »")],
        budget: Annotated[bool, typer.Option(help="compte suivi par le budget")] = True,
        liquid: Annotated[bool, typer.Option(help="compte dans les liquidités")] = True,
    ) -> None:
        """Crée le compte (proposition validée au terminal), l'ouvre avec le solde déduit de la
        reprise complète, puis applique ses relevés en attente."""
        ready()
        m = re.fullmatch(r"revolut:([A-Z]{3})(:[a-z0-9-]+)?", ref)
        if m is None:
            typer.echo("clé attendue : revolut:CHF ou revolut:EUR:produit", err=True)
            raise typer.Exit(1)
        with engine.connect() as conn:
            account = catalog.account_by_ref(conn, ref)
        created = account is None
        if account is None:
            result = propose_and_accept(
                host,
                "create_account",
                {
                    "institution": "Revolut",
                    "name": name,
                    "kind": "cash",
                    "currency": m.group(1),
                    "external_ref": ref,
                    "liquid": liquid,
                    "budget_account": budget,
                },
            )
            with engine.connect() as conn:
                account = catalog.get_account(conn, str(result["account_id"]))
        with engine.connect() as conn:
            opened = conn.execute(
                text("SELECT 1 FROM entries WHERE account_id = :a LIMIT 1"), {"a": account.id}
            ).first()
        if opened and created:  # la validation l'a ouvert (même chemin que l'app, G5)
            _out({"id": account.id, "opened": True, "imports": None})
            return
        if opened:
            outcomes = host.importer.retry_needs_review()
            _out({"id": account.id, "opened": False, "retried": len(outcomes)})
            return
        done, ids = revolut_accounts.open_revolut(host.importer, account)
        if not done:
            typer.echo(
                "aucun relevé avec solde : ouvrir à la main (hub finance accounts open)", err=True
            )
        _out({"id": account.id, "opened": done, "imports": len(ids)})

    def create_positions_account(
        ref: str, institution: str, name: str, kind: str, currency: str | None = None
    ) -> str:
        """Compte à positions, créé par une proposition validée au terminal (idempotent)."""
        with engine.connect() as conn:
            found = catalog.account_by_ref(conn, ref)
        if found is not None:
            return found.id
        result = propose_and_accept(
            host,
            "create_account",
            {
                "institution": institution,
                "name": name,
                "kind": kind,
                "currency": currency or base_currency(),
                "external_ref": ref,
            },
        )
        return str(result["account_id"])

    @ibkr_app.command("add-account")
    def ibkr_add_account(
        number: Annotated[str, typer.Argument(help="n° de compte IBKR, ex. U1234567")],
        name: Annotated[str, typer.Option(help="ex. « IBKR »")] = "IBKR",
        base: Annotated[
            str | None, typer.Option(help="devise de base du compte IBKR (celle du hub)")
        ] = None,
    ) -> None:
        """Déclare un compte IBKR : son compte de titres (proposition validée au terminal). Les
        comptes de liquidités par devise se créent au premier relevé Flex qui les cite."""
        ready()
        if not re.fullmatch(r"[A-Z0-9]{4,20}", number):
            typer.echo("numéro attendu : U1234567", err=True)
            raise typer.Exit(1)
        account_id = create_positions_account(
            ibkr_flex.titles_ref(number),
            "IBKR",
            f"{name} titres",
            "securities",
            (base or base_currency()).upper(),
        )
        _out({"id": account_id, "ref": ibkr_flex.titles_ref(number)})

    @ibkr_app.command("import-history")
    def ibkr_import_history(
        folder: Annotated[Path, typer.Argument(exists=True, file_okay=False)],
    ) -> None:
        """Reprise des relevés Flex (XML, sous-dossiers compris), du plus ancien au plus récent :
        le plus ancien ouvre les comptes au solde de départ d'IBKR. Compteurs seuls."""
        ready()
        report = history.import_ibkr_history(host.importer, folder)
        _out(report.public())
        if not report.ok:
            raise typer.Exit(1)

    @crypto_app.command("add-wallet")
    def crypto_add_wallet(
        name: Annotated[str, typer.Argument(help="nom court, ex. ledger-btc")],
        label: Annotated[str | None, typer.Option(help="nom affiché")] = None,
    ) -> None:
        """Déclare un portefeuille crypto (compte `crypto:<nom>`, dans la devise de base) ; ses
        adresses vont dans les secrets du collecteur « market », jamais dans la base."""
        ready()
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,40}", name):
            typer.echo("nom attendu : minuscules, chiffres et tirets (ledger-btc)", err=True)
            raise typer.Exit(1)
        ref = f"crypto:{name}"
        account_id = create_positions_account(ref, "Crypto", label or name, "crypto")
        _out({"id": account_id, "ref": ref})

    @positions_app.command("add-account")
    def positions_add_account(
        ref: Annotated[str, typer.Argument(help="référence, ex. revolut:invest")],
        name: Annotated[str, typer.Option(help="ex. « Revolut actions »")],
        institution: Annotated[str, typer.Option(help="ex. Revolut")],
        kind: Annotated[str, typer.Option(help="securities ou crypto")] = "securities",
    ) -> None:
        """Compte dont les positions arrivent par un CSV saisi à la main
        (date,account,instrument,name,kind,quantity,price,currency)."""
        ready()
        if kind not in ("securities", "crypto") or not re.fullmatch(
            r"[a-z0-9]+:[a-z0-9][a-z0-9:-]{0,40}", ref
        ):
            typer.echo("référence : revolut:invest ; type : securities ou crypto", err=True)
            raise typer.Exit(1)
        account_id = create_positions_account(ref, institution, name, kind)
        _out({"id": account_id, "ref": ref})

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

    @imports.command("replay")
    def imports_replay(
        source: Annotated[str, typer.Argument(help="source des documents, ex. swissborg")],
    ) -> None:
        """Réapplique les documents déjà importés d'une source, depuis l'archive chiffrée
        (après une évolution de l'importeur : opérations SwissBorg au registre, par exemple)."""
        ready()
        try:
            outcomes = host.importer.replay(source)
        except errors.ImportRefused as exc:
            typer.echo(exc.detail, err=True)
            raise typer.Exit(1) from exc
        _out(
            {
                "statements": len(outcomes),
                "applied": sum(o.status == "applied" for o in outcomes),
                "needs_review": sum(o.status == "needs_review" for o in outcomes),
                "new": sum(o.new for o in outcomes),
                "duplicates": sum(o.duplicates for o in outcomes),
            }
        )

    @imports.command("retry")
    def imports_retry(ids: Annotated[list[str] | None, typer.Argument()] = None) -> None:
        """Rejoue les relevés en attente depuis l'archive chiffrée."""
        ready()
        try:
            outcomes = host.importer.retry_needs_review(ids or None)
        except errors.ImportRefused as exc:
            typer.echo(exc.detail, err=True)
            raise typer.Exit(1) from exc
        _out(
            {
                "retried": len(outcomes),
                "applied": sum(o.status == "applied" for o in outcomes),
                "still_needs_review": sum(o.status == "needs_review" for o in outcomes),
            }
        )
