"""Commande `hub` : serveur, migrations, jetons, amorçage des passkeys, tâches de fond."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Annotated, Any

import typer
import yaml

from hub.core import connections, connectors, profile, proposals, secrets, sessions, tokens
from hub.core import logging as hub_logging
from hub.core.auth import Principal
from hub.core.context import HubContext
from hub.core.errors import Problem
from hub.core.registry import Registry
from hub.core.settings import get_settings

app = typer.Typer(no_args_is_help=True, add_completion=False, help="Personal Hub")
db_app = typer.Typer(no_args_is_help=True, help="Bases et migrations")
token_app = typer.Typer(no_args_is_help=True, help="Jetons à portée")
auth_app = typer.Typer(no_args_is_help=True, help="Passkeys")
app.add_typer(db_app, name="db")
app.add_typer(token_app, name="token")
app.add_typer(auth_app, name="auth")
proposals_app = typer.Typer(no_args_is_help=True, help="Propositions (Double Sas)")
app.add_typer(proposals_app, name="proposals")
profile_app = typer.Typer(no_args_is_help=True, help="Profil de l'instance (prénom, pays)")
app.add_typer(profile_app, name="profile")
connections_app = typer.Typer(no_args_is_help=True, help="Connexions des collecteurs (G4)")
app.add_typer(connections_app, name="connections")

CLI_ACTOR = "system:cli"


def _ctx() -> HubContext:
    settings = get_settings()
    hub_logging.configure(settings.log_level, stream=sys.stderr)
    return HubContext.build(settings)


def _ready() -> HubContext:
    hub = _ctx()
    if not hub.core.is_current():
        typer.echo("core.db n'est pas à jour : lancer `hub db upgrade`.", err=True)
        raise typer.Exit(2)
    return hub


@app.command()
def serve(
    workers: Annotated[
        int, typer.Option(min=1, max=1, help="Un seul worker (aucun état partagé en mémoire).")
    ] = 1,
    migrate: Annotated[bool, typer.Option(help="Migrer au démarrage (développement).")] = False,
) -> None:
    """Lance l'API (uvicorn)."""
    import uvicorn

    from hub.api.app import create_app

    hub = _ctx()
    if not migrate and not hub.core.is_current():
        typer.echo("core.db n'est pas à jour : lancer `hub db upgrade`.", err=True)
        raise typer.Exit(2)
    settings = hub.settings
    uvicorn.run(
        create_app(hub, migrate=migrate),
        host=settings.server.host,
        port=settings.server.port,
        workers=workers,
        log_config=None,
        access_log=False,
        proxy_headers=True,
        forwarded_allow_ips="*",
    )


@db_app.command("upgrade")
def db_upgrade() -> None:
    """Monte `core.db` puis chaque base de domaine à la dernière version."""
    hub = _ctx()
    hub.migrate_all()
    typer.echo(json.dumps({"core": hub.core.revision(), "domains": hub.registry.names()}))


@db_app.command("status")
def db_status() -> None:
    hub = _ctx()
    typer.echo(
        json.dumps(
            {
                "core": {"revision": hub.core.revision(), "current": hub.core.is_current()},
                "domains": {d.name: d.health().db for d in hub.registry},
            }
        )
    )


@token_app.command("create")
def token_create(
    name: Annotated[str, typer.Argument(help="ex. brain-mac, collector-api")],
    scope: Annotated[
        list[str],
        typer.Option(
            "--scope", "-s", help="brain, aggregates, collector ou portée qualifiée finance:read"
        ),
    ],
) -> None:
    """Crée un jeton. Il n'est affiché qu'une fois : seule son empreinte est gardée."""
    hub = _ready()
    try:
        with hub.core.engine.begin() as conn:
            info, secret = tokens.create(conn, name, scope, CLI_ACTOR)
    except tokens.ScopeError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"id      : {info.id}\nportées : {' '.join(info.scopes)}", err=True)
    typer.echo("jeton (affiché une seule fois) :", err=True)
    typer.echo(secret)


@token_app.command("list")
def token_list() -> None:
    hub = _ready()
    with hub.core.engine.connect() as conn:
        for t in tokens.list_all(conn):
            state = "révoqué" if t.revoked_at else "actif"
            typer.echo(
                f"{t.id}  {t.name:<20} {state:<8} {' '.join(t.scopes)}  "
                f"dernier usage : {t.last_used_at or 'jamais'}"
            )


@token_app.command("revoke")
def token_revoke(token_id: str) -> None:
    hub = _ready()
    with hub.core.engine.begin() as conn:
        done = tokens.revoke(conn, token_id, CLI_ACTOR)
    typer.echo("révoqué" if done else "inconnu ou déjà révoqué")
    if not done:
        raise typer.Exit(1)


@auth_app.command("bootstrap-code")
def bootstrap_code() -> None:
    """Code à usage unique pour inscrire une passkey depuis l'app (valable quelques minutes)."""
    hub = _ready()
    with hub.core.engine.begin() as conn:
        code = sessions.create_bootstrap_code(conn, hub.settings.auth.bootstrap_minutes, CLI_ACTOR)
    typer.echo(f"valable {hub.settings.auth.bootstrap_minutes} minutes :", err=True)
    typer.echo(code)


@profile_app.command("show")
def profile_show() -> None:
    """Profil de l'instance, en JSON ; le fuseau vient de HUB_TZ."""
    hub = _ready()
    with hub.core.engine.connect() as conn:
        typer.echo(json.dumps(profile.get(conn).public(), ensure_ascii=False))


@profile_app.command("set")
def profile_set(
    name: Annotated[str | None, typer.Option(help="Prénom employé par l'assistant.")] = None,
    country: Annotated[
        str | None, typer.Option(help="Pays (ISO, ex. CH) : ouvre les modules du pays.")
    ] = None,
    clear_name: Annotated[bool, typer.Option("--clear-name", help="Efface le prénom.")] = False,
) -> None:
    """Change le prénom ou le pays de l'instance."""
    hub = _ready()
    try:
        with hub.core.engine.begin() as conn:
            p = profile.update(
                conn, CLI_ACTOR, display_name=name, country=country, clear_name=clear_name
            )
    except profile.ProfileError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from None
    typer.echo(json.dumps(p.public(), ensure_ascii=False))


@connections_app.command("list")
def connections_list() -> None:
    """Connexions de l'instance, une par ligne en JSON ; jamais leurs secrets."""
    hub = _ready()
    with hub.core.engine.connect() as conn:
        for c in connections.list_all(conn):
            typer.echo(json.dumps(c.public(), ensure_ascii=False))


@connections_app.command("catalog")
def connections_catalog() -> None:
    """Connecteurs disponibles : méthode, secrets et réglages attendus."""
    for c in connectors.CATALOG:
        typer.echo(json.dumps(c.public(), ensure_ascii=False))


def _settings_option(raw: str | None) -> dict[str, Any] | None:
    if raw is None:
        return None
    value = json.loads(raw)
    if not isinstance(value, dict):
        typer.echo("--settings : un objet JSON", err=True)
        raise typer.Exit(2)
    return value


@connections_app.command("add")
def connections_add(
    connection_id: Annotated[str, typer.Argument(help="identifiant, ex. bcf ou n26")],
    connector: Annotated[str, typer.Argument(help="entrée du catalogue, ex. enable_banking")],
    label: Annotated[str | None, typer.Option(help="nom affiché")] = None,
    schedule: Annotated[str | None, typer.Option(help="cron ; par défaut, le catalogue")] = None,
    settings: Annotated[str | None, typer.Option(help="réglages, objet JSON")] = None,
) -> None:
    """Ajoute une connexion ; ses secrets se donnent ensuite (`hub connections secrets`)."""
    hub = _ready()
    try:
        with hub.core.engine.begin() as conn:
            c = connections.create(
                conn,
                connection_id,
                connector,
                CLI_ACTOR,
                label=label,
                schedule=schedule,
                settings=_settings_option(settings),
            )
    except Problem as exc:
        raise _problem_exit(exc) from None
    typer.echo(json.dumps(c.public(), ensure_ascii=False))


@connections_app.command("set")
def connections_set(
    connection_id: str,
    label: Annotated[str | None, typer.Option()] = None,
    schedule: Annotated[str | None, typer.Option(help="cron, fuseau HUB_TZ")] = None,
    default_schedule: Annotated[
        bool, typer.Option("--default-schedule", help="revient à l'horaire du catalogue")
    ] = False,
    settings: Annotated[str | None, typer.Option(help="réglages, objet JSON (remplace)")] = None,
) -> None:
    """Change le nom, l'horaire ou les réglages d'une connexion."""
    hub = _ready()
    try:
        with hub.core.engine.begin() as conn:
            c = connections.update(
                conn,
                connection_id,
                CLI_ACTOR,
                label=label,
                schedule=schedule,
                default_schedule=default_schedule,
                settings=_settings_option(settings),
            )
    except Problem as exc:
        raise _problem_exit(exc) from None
    typer.echo(json.dumps(c.public(), ensure_ascii=False))


@connections_app.command("secrets")
def connections_secrets(
    connection_id: str,
    file: Annotated[
        Path | None,
        typer.Option(help="YAML des secrets (ex. wallets), `-` pour l'entrée standard"),
    ] = None,
) -> None:
    """Remplace les secrets d'une connexion : tapés masqués (ou lus d'un YAML), chiffrés vers la
    clé de la machine. Ils ne sont plus jamais affichés."""
    hub = _ready()
    try:
        with hub.core.engine.connect() as conn:
            current = connections.require(conn, connection_id)
    except Problem as exc:
        raise _problem_exit(exc) from None
    spec = current.spec
    if file is not None:
        values = yaml.safe_load(sys.stdin.read() if str(file) == "-" else file.read_text())
        if not isinstance(values, dict):
            typer.echo("le YAML doit contenir un dictionnaire", err=True)
            raise typer.Exit(2)
    else:
        fields = spec.secrets if spec else ()
        values = {k: typer.prompt(k, hide_input=True) for k in fields}
    recipient = secrets.recipient(hub.settings.secrets.age_key_file)
    try:
        with hub.core.engine.begin() as conn:
            c = connections.set_secrets(conn, connection_id, values, recipient, CLI_ACTOR)
    except Problem as exc:
        raise _problem_exit(exc) from None
    typer.echo(json.dumps(c.public(), ensure_ascii=False))


@connections_app.command("remove")
def connections_remove(connection_id: str) -> None:
    """Retire une connexion et son état ; l'historique des runs reste."""
    hub = _ready()
    try:
        with hub.core.engine.begin() as conn:
            connections.delete(conn, connection_id, CLI_ACTOR)
    except Problem as exc:
        raise _problem_exit(exc) from None
    typer.echo("retirée")


def _service_files(hub: HubContext, folder: Path) -> list[str]:
    """Un fichier de secrets par service collecteur, avec son jeton `core:collector`, s'il
    n'existe pas encore. Le jeton n'est jamais affiché."""
    recipient = secrets.recipient(hub.settings.secrets.age_key_file)
    written = []
    for runner in connectors.RUNNERS:
        path = folder / f"collector-{runner}.enc.yaml"
        if path.exists():
            continue
        with hub.core.engine.begin() as conn:
            _info, secret = tokens.create(conn, f"collector-{runner}", ["collector"], CLI_ACTOR)
            plain = yaml.safe_dump({f"collector-{runner}": {"token": secret}}).encode()
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(secrets.encrypt_for(recipient, plain))
            os.chmod(tmp, 0o600)
            tmp.replace(path)
        written.append(path.name)
    return written


@connections_app.command("import")
def connections_import(
    folder: Annotated[Path, typer.Argument(exists=True, file_okay=False)],
    service_files: Annotated[
        bool, typer.Option(help="écrit aussi collector-api/browser.enc.yaml s'ils manquent")
    ] = True,
) -> None:
    """Reprise d'avant G4 : les `<nom>.enc.yaml` des anciens conteneurs deviennent les secrets
    des connexions (une connexion qui a déjà les siens les garde), puis les fichiers des deux
    services sont écrits avec leur jeton. Sans danger à relancer. Compteurs seuls."""
    hub = _ready()
    key_file = hub.settings.secrets.age_key_file
    try:
        with hub.core.engine.begin() as conn:
            report = connections.import_legacy(
                conn, folder, key_file, CLI_ACTOR, dict(hub.settings.domain("collectors"))
            )
    except (Problem, secrets.SecretsError) as exc:
        typer.echo(f"reprise impossible : {exc}", err=True)
        raise typer.Exit(1) from None
    written = _service_files(hub, folder) if service_files else []
    typer.echo(json.dumps({**report.public(), "service_files": written}, ensure_ascii=False))


def _cli_principal() -> Principal:
    """Le terminal de la machine vaut validation : qui l'ouvre tient déjà le disque."""
    return Principal(CLI_ACTOR, frozenset(), is_app=True)


def _problem_exit(exc: Problem) -> typer.Exit:
    typer.echo(json.dumps(exc.body(), ensure_ascii=False), err=True)
    return typer.Exit(1)


@proposals_app.command("list")
def proposals_list(
    status: Annotated[str, typer.Option(help="pending, applied, rejected… ou all")] = "pending",
    limit: Annotated[int, typer.Option(min=1, max=200)] = 50,
) -> None:
    hub = _ready()
    proposals.sync_events(hub)
    with hub.core.engine.connect() as conn:
        items = proposals.list_by_status(conn, None if status == "all" else status, limit)
    for p in items:
        typer.echo(
            f"{p.id}  {p.domain}/{p.kind:<16} {p.status:<10} r{p.revision}  "
            f"{p.preview.get('summary', '')}"
        )


@proposals_app.command("show")
def proposals_show(proposal_id: str) -> None:
    hub = _ready()
    try:
        with hub.core.engine.connect() as conn:
            p = proposals.get(conn, proposal_id)
    except Problem as exc:
        raise _problem_exit(exc) from exc
    typer.echo(json.dumps(p.public(), ensure_ascii=False, indent=1))


@proposals_app.command("accept")
def proposals_accept(ids: Annotated[list[str], typer.Argument()]) -> None:
    """Valide depuis le terminal ; chaque proposition s'applique seule. Code 1 si l'une échoue."""
    hub = _ready()
    try:
        items = proposals.load_many(hub, ids)
    except Problem as exc:
        raise _problem_exit(exc) from exc
    results = proposals.accept(hub, _cli_principal(), items, None)
    for r in results:
        typer.echo(json.dumps(r.public(), ensure_ascii=False))
    if any(r.status != "applied" for r in results):
        raise typer.Exit(1)


@proposals_app.command("reject")
def proposals_reject(proposal_id: str) -> None:
    hub = _ready()
    try:
        p = proposals.reject(hub, _cli_principal(), proposal_id)
    except Problem as exc:
        raise _problem_exit(exc) from exc
    typer.echo(json.dumps({"id": p.id, "status": p.status}))


@proposals_app.command("create")
def proposals_create(
    domain: str,
    kind: str,
    params: Annotated[str, typer.Option(help="paramètres en JSON")] = "{}",
    reason: Annotated[str | None, typer.Option()] = None,
    accept: Annotated[bool, typer.Option(help="valider aussitôt")] = False,
) -> None:
    """Crée une proposition (aperçu affiché) ; `--accept` la valide dans la foulée."""
    hub = _ready()
    try:
        values = json.loads(params)
    except json.JSONDecodeError as exc:
        typer.echo("paramètres : JSON invalide", err=True)
        raise typer.Exit(1) from exc
    try:
        p, _created = proposals.create(hub, _cli_principal(), domain, kind, values, reason=reason)
        typer.echo(json.dumps(p.public(), ensure_ascii=False, indent=1))
        if accept and p.status == "pending":
            (outcome,) = proposals.accept(hub, _cli_principal(), [p], None)
            typer.echo(json.dumps(outcome.public(), ensure_ascii=False))
            if outcome.status != "applied":
                raise typer.Exit(1)
    except Problem as exc:
        raise _problem_exit(exc) from exc


@app.command()
def init(
    config: Annotated[Path, typer.Option(help="Clé age et secrets (ex. ~/.config/hub).")],
    home: Annotated[Path, typer.Option(help="Boîte d'entrée et sauvegardes locales.")],
    env_file: Annotated[Path, typer.Option("--env", help="Fichier écrit.")] = Path("deploy/.env"),
    template: Annotated[Path, typer.Option(help="Modèle.")] = Path("deploy/.env.example"),
    origin: Annotated[
        str, typer.Option(help="Adresse Tailscale du hub, connue après le 1er démarrage.")
    ] = "https://hub.votre-tailnet.ts.net",
    tz: Annotated[str, typer.Option(help="Fuseau (IANA).")] = "Europe/Zurich",
    currency: Annotated[str, typer.Option(help="Devise de base, fixée ensuite.")] = "CHF",
    country: Annotated[str, typer.Option(help="Pays (ISO, deux lettres).")] = "CH",
) -> None:
    """Prépare une première installation : clé age, secrets chiffrés, dossiers et deploy/.env.
    Ne remplace rien de ce qui existe."""
    from hub.core import install

    choices = install.Choices(config, home, origin, tz, currency, country)
    try:
        report = install.run(choices, env_file, template)
    except (install.InitError, secrets.SecretsError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from None
    for path in report.created:
        typer.echo(f"créé    {path}")
    for path in report.kept:
        typer.echo(f"gardé   {path}")
    typer.echo(f"clé publique age : {report.public_key}")


@app.command()
def nightly() -> None:
    """Expiration des propositions, purges, réconciliation, tâches de nuit des domaines."""
    from hub.core.maintenance import nightly as run

    typer.echo(json.dumps(run(_ready())))


@app.command()
def reconcile() -> None:
    """Recale les statuts des propositions sur `applied_proposals` (après une restauration)."""
    hub = _ready()
    report = proposals.reconcile(hub)
    typer.echo(json.dumps({"applied": report.marked_applied, "released": report.released}))


@app.command()
def verify() -> None:
    """Intégrité de chaque base et santé des domaines ; code de sortie 1 au moindre écart."""
    from hub.core.maintenance import verify as run

    report = run(_ctx())
    typer.echo(json.dumps({"ok": report.ok, "checks": report.checks}))
    if not report.ok:
        raise typer.Exit(1)


@app.command()
def backup(
    dest: Annotated[Path | None, typer.Option(help="Dossier cible (défaut : paths.backup)")] = None,
    stamp: Annotated[str | None, typer.Option(help="Suffixe des fichiers (défaut : date)")] = None,
    restic: Annotated[bool, typer.Option(help="Puis restic vers chaque dépôt.")] = False,
) -> None:
    """Copie `.backup` cohérente de chaque base, vérifiée par `integrity_check`."""
    from hub.core.maintenance import backup_all, prune_local_copies, restic_backup

    hub = _ctx()
    target = dest or hub.settings.paths.backup
    files = backup_all(hub, target, stamp)
    out: dict[str, object] = {"files": [f.name for f in files]}
    if restic:
        out["pruned"] = prune_local_copies(target, hub.settings.backup.keep_local_days)
        out["restic"] = len(restic_backup(hub))
    typer.echo(json.dumps(out))


@app.command()
def restore(
    stamp: Annotated[str, typer.Argument(help="Suffixe des copies, ex. predeploy-v0.2.0")],
    source: Annotated[Path | None, typer.Option(help="Dossier des copies")] = None,
) -> None:
    """Remet les bases depuis une copie de `hub backup` (services arrêtés), puis réconcilie."""
    from hub.core.maintenance import restore as run

    try:
        restored = run(_ctx(), stamp, source)
    except (FileNotFoundError, RuntimeError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    typer.echo(json.dumps({"restored": restored}))


@app.command()
def scheduler(crontab: Path) -> None:
    """Exécute la crontab du dépôt (conteneur `scheduler`)."""
    from hub.core.cron import run_forever

    hub_logging.configure(get_settings().log_level)
    run_forever(crontab)


def main() -> None:
    # sous-commandes fournies par les domaines (`hub finance …`), sans que le cœur les importe
    try:
        for domain in Registry.discover(get_settings()):
            sub = domain.cli()
            if sub is not None:
                app.add_typer(sub, name=domain.name)
    except Exception as exc:  # un domaine cassé ne doit pas empêcher `hub db …`
        typer.echo(f"domaines non chargés : {type(exc).__name__}", err=True)
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
