#!/usr/bin/env bash
# Restauration depuis la réplique Litestream dans un projet compose vierge (critère de L0-08).
#   deploy/restore-test.sh [tag]
# Ne touche à rien du projet « hub » : tout se passe dans le projet jetable « hub-restore-test ».
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
TAG="${1:-$(cat "$HERE/.current-tag" 2>/dev/null || echo dev)}"
# shellcheck disable=SC1091
set -a; . "$HERE/.env"; set +a
P=(docker compose -p hub-restore-test --project-directory "$HERE" -f "$HERE/compose.yaml" --env-file "$HERE/.env")
export HUB_TAG="$TAG"

cleanup() { "${P[@]}" down -v --remove-orphans >/dev/null 2>&1 || true; }
trap cleanup EXIT

# le volume « data » doit naître de l'image du hub (propriétaire 10001), pas de celle de Litestream
"${P[@]}" run --rm --no-deps scheduler true
echo "==> Restauration de core.db depuis $HUB_REPLICA"
"${P[@]}" run --rm --no-deps --entrypoint litestream litestream \
  restore -config /etc/litestream.yml -o /srv/hub/data/core.db /srv/hub/data/core.db
echo "==> Vérification de la base restaurée"
"${P[@]}" run --rm --no-deps scheduler hub verify
"${P[@]}" run --rm --no-deps scheduler hub reconcile
echo "==> Restauration réussie (projet jetable supprimé à la sortie)"
