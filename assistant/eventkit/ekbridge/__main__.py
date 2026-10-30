"""`python -m ekbridge [--port 8771] [--authorize]` : le pont sur 127.0.0.1. `--authorize` demande l'accès à Rappels et
Calendrier (à lancer une fois depuis le Terminal) ; au démarrage, l'état de l'autorisation est écrit au journal."""

from __future__ import annotations

import argparse
import contextlib
import logging
import sys

from .eventkit import EventKitStore
from .http import serve

log = logging.getLogger("ekbridge")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ekbridge")
    parser.add_argument("--port", type=int, default=8771)
    parser.add_argument("--authorize", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s ekbridge %(message)s")
    store = EventKitStore()
    if args.authorize or not all(store.access().values()):
        store.request()  # dans l'app de make-app.sh, macOS ouvre sa fenêtre pour l'app ; une seule fois
    access = store.access()
    log.info("access reminders=%s calendar=%s", access["reminders"], access["calendar"])
    if not all(access.values()):
        log.warning(
            "Rappels ou Calendrier non autorisés : lancer l'app « Domia Rappels » (eventkit/make-app.sh) et accepter ses fenêtres"
        )
    server = serve(store, args.port)
    log.info("listening port=%d", args.port)
    with contextlib.suppress(KeyboardInterrupt):
        server.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
