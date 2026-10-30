"""Exploitation sans liste en dur (chantier S7) : les bases viennent du registre des domaines.

`hub ops databases` les liste (restauration, sauvegarde), `hub ops litestream` écrit la
configuration de réplication que `deploy.sh` monte dans le conteneur Litestream.
"""

from __future__ import annotations

from pathlib import PurePosixPath

from hub.core.context import HubContext

CONTAINER_DATA = PurePosixPath("/srv/hub/data")  # chemin des bases dans les conteneurs
REPLICA = PurePosixPath("/replica")

HEADER = """\
# Réplication continue vers le disque externe monté (HUB_REPLICA). Le second emplacement est
# couvert par restic (conteneur « scheduler »), qui sauvegarde aussi cette réplique.
# Écrit par `hub ops litestream` depuis le registre des domaines (chantier S7) : ne pas éditer.
"""


def database_names(hub: HubContext) -> list[str]:
    """`core`, puis chaque domaine monté, dans l'ordre du registre."""
    return ["core", *hub.registry.names()]


def litestream_config(hub: HubContext) -> str:
    lines = [HEADER.rstrip("\n"), "dbs:"]
    for name in database_names(hub):
        lines += [
            f"  - path: {CONTAINER_DATA / f'{name}.db'}",
            "    replica:",
            "      type: file",
            f"      path: {REPLICA / f'{name}.db'}",
        ]
    return "\n".join(lines) + "\n"
