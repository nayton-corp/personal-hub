"""Commandes `hub finance …` : registre, comptes et catégories, règles, imports, reprise
d'historique.

Créer un compte ou une catégorie passe par le Double Sas (ticket L1-12, bascule du lot 3) : la
commande crée la proposition et la valide depuis le terminal. Les sorties sont des
identifiants et des compteurs, jamais le contenu d'une écriture.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer
from sqlalchemy import text

from hub.core import proposals
from hub.core.auth import Principal
from hub.core.context import HubContext
from hub.core.errors import Problem
from hub.core.registry import Registry
from hub.domains.finance import catalog, ibkr, importer, legacy, packs, rebuild, rules
from hub.domains.finance import viac as viac_patterns
from hub.domains.finance.viac import apply as viac_apply
from hub.kernel.money import Money, base_currency
from hub.kernel.text import mask_iban
from hub.platform.db import begin_immediate, make_engine

if TYPE_CHECKING:
    from hub.domains.finance.domain import FinanceDomain


CLI = Principal("system:cli", frozenset(), is_app=True)


def _out(value: object) -> None:
    typer.echo(json.dumps(value, ensure_ascii=False))


def propose_and_accept(
    domain: FinanceDomain, kind: str, params: dict[str, object]
) -> dict[str, object]:
    """Crée la proposition et la valide depuis le terminal ; renvoie son résultat."""
    hub = HubContext.build(domain.settings, Registry([domain]))
    if not hub.core.is_current():
        typer.echo("core.db n'est pas à jour : lancer `hub db upgrade`.", err=True)
        raise typer.Exit(2)
    try:
        p, _ = proposals.create(hub, CLI, "finance", kind, params)
        if p.status == "applied":
            return {"proposal_id": p.id, **(p.result or {})}
        (outcome,) = proposals.accept(hub, CLI, [p], None)
    except Problem as exc:
        typer.echo(exc.detail or exc.title, err=True)
        raise typer.Exit(1) from exc
    finally:
        hub.core.dispose()
    if outcome.status != "applied":
        problem = outcome.problem or {}
        typer.echo(str(problem.get("detail") or problem.get("title") or outcome.status), err=True)
        raise typer.Exit(1)
    return {"proposal_id": p.id, **(outcome.result or {})}


def build_cli(domain: FinanceDomain) -> typer.Typer:
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
            domain,
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
        """Crée une catégorie par une proposition `create_category` validée depuis le terminal."""
        ready()
        result = propose_and_accept(
            domain, "create_category", {"id": id, "name": name, "grp": group}
        )
        _out({"id": id, "proposal": result["proposal_id"]})

    @categories.command("list")
    def categories_list() -> None:
        ready()
        with engine.connect() as conn:
            for c in catalog.list_categories(conn):
                typer.echo(f"{c.id:<20} {c.grp:<9} {c.name}{'' if c.active else ' (inactive)'}")

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

    @app.command("watch-inbox")
    def watch_inbox(
        poll: Annotated[int, typer.Option(min=1, help="secondes entre deux passages")] = 30,
        once: Annotated[bool, typer.Option(help="un seul passage")] = False,
    ) -> None:
        """Surveille `inbox/` (xml, zip et PDF VIAC) ; traite tout ce qui est prêt."""
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
        from hub.domains.finance.domain import FinanceDomain

        paths = domain.settings.paths.model_copy(update={"data": out})
        target = FinanceDomain(domain.settings.model_copy(update={"paths": paths}))
        target.importer.pdf_text = domain.importer.pdf_text
        hub = HubContext.build(domain.settings, Registry([domain]))
        try:
            applied = rebuild.applied_proposals(engine, hub.core.engine)
        finally:
            hub.core.dispose()
        try:
            report = rebuild.rebuild(domain, target, applied)
            diff = rebuild.compare(engine, target.engine())
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
            diff = rebuild.compare(engine, other_engine)
        finally:
            other_engine.dispose()
        _out(diff.public())
        if not diff.ok:
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
                domain,
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
        report = importer.import_viac_history(domain.importer, folder)
        _out(report.public())
        if not report.ok:
            raise typer.Exit(1)

    @revolut_app.command("pending")
    def revolut_pending() -> None:
        """Comptes Revolut vus dans des fichiers en attente : clé, nombre d'écritures, période,
        motifs. Aucun montant."""
        ready()
        out = []
        for ref, items in sorted(importer.revolut_pending(domain.importer).items()):
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
                domain,
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
            outcomes = domain.importer.retry_needs_review()
            _out({"id": account.id, "opened": False, "retried": len(outcomes)})
            return
        done, ids = importer.open_revolut(domain.importer, account)
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
            domain,
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
            ibkr.titles_ref(number),
            "IBKR",
            f"{name} titres",
            "securities",
            (base or base_currency()).upper(),
        )
        _out({"id": account_id, "ref": ibkr.titles_ref(number)})

    @ibkr_app.command("import-history")
    def ibkr_import_history(
        folder: Annotated[Path, typer.Argument(exists=True, file_okay=False)],
    ) -> None:
        """Reprise des relevés Flex (XML, sous-dossiers compris), du plus ancien au plus récent :
        le plus ancien ouvre les comptes au solde de départ d'IBKR. Compteurs seuls."""
        ready()
        report = importer.import_ibkr_history(domain.importer, folder)
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

    @app.command("derived")
    def derived_cmd() -> None:
        """Recalcule les instantanés, les virements appariés et les abonnements."""
        ready()
        refreshed = domain.refresh_snapshots(force=True)
        _out({"snapshots": refreshed.rows, **domain.refresh_derived()})

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
            outcomes = domain.importer.replay(source)
        except importer.ImportRefused as exc:
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
