#!/usr/bin/env bash
# Déploiement phase 1 (spécification, section 10.0) : images au lieu d'un clone git.
#   deploy/deploy.sh <tag>
# 1. construit les images linux/arm64 ; 2. verify dans un conteneur jetable (arrêt si échec) ;
# 3. copie .backup des bases ; 4. migrations ; 5. second verify, sinon restauration et retour
# à l'image précédente ; 6. connexions des collecteurs (reprise d'avant G4, fichiers des deux
# services) ; 7. compose up ; 8. /api/health dans les 30 s, sinon retour arrière.
set -euo pipefail

TAG="${1:?usage: deploy/deploy.sh <tag>}"
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
STATE="$HERE/.current-tag"
PLATFORM="${HUB_PLATFORM:-linux/arm64}"
PREV="$(cat "$STATE" 2>/dev/null || true)"
STAMP="predeploy-$TAG"

compose() { HUB_TAG="$1" docker compose --project-directory "$HERE" -f "$HERE/compose.yaml" \
  --env-file "$HERE/.env" "${@:2}"; }
once() { compose "$1" run --rm --no-deps scheduler "${@:2}"; }
say() { printf '\n==> %s\n' "$*"; }

[ -f "$HERE/.env" ] || { echo "deploy/.env manquant (copier deploy/.env.example)"; exit 1; }
# shellcheck disable=SC1091
set -a; . "$HERE/.env"; set +a

if [ -z "${HUB_SKIP_BUILD:-}" ]; then
  say "Construction des images $TAG ($PLATFORM)"
  docker build --platform "$PLATFORM" --target hub -t "hub:$TAG" "$ROOT"
  docker build --platform "$PLATFORM" --target web -t "hub-web:$TAG" "$ROOT"
  docker build --platform "$PLATFORM" --target collector -t "hub-collector:$TAG" "$ROOT"
fi

first_deploy=0
if ! once "$TAG" sh -c 'test -f /srv/hub/data/core.db'; then
  first_deploy=1
  say "Premier déploiement : aucune base existante"
fi

if [ "$first_deploy" = 0 ]; then
  say "Vérification avant migration"
  # l'image en place : la nouvelle voit un schéma « pas à jour » tant que la migration n'a pas eu lieu
  once "${PREV:-$TAG}" hub verify || { echo "verify échoue AVANT migration : arrêt, rien n'a changé"; exit 1; }
  say "Arrêt des services qui écrivent, puis copie des bases ($STAMP)"
  compose "${PREV:-$TAG}" stop api importer scheduler litestream 2>/dev/null || true
  once "${PREV:-$TAG}" hub backup --stamp "$STAMP"
fi

# G4 : les volumes des anciens conteneurs (un par collecteur) sont recopiés une fois dans ceux
# des deux services, pour garder les profils du navigateur (appareil reconnu par la banque) et
# la mémoire (session Enable Banking, empreintes déjà vues). Les anciens volumes restent.
merge_collector_volumes() {
  local old target
  for old in bcf viac revolut ibkr market binance kucoin coinbase; do
    docker volume inspect "hub_collector-$old" >/dev/null 2>&1 || continue
    case "$old" in bcf|viac) target=browser ;; *) target=api ;; esac
    docker volume inspect "hub_collector-$target" >/dev/null 2>&1 || docker volume create \
      --label com.docker.compose.project=hub --label "com.docker.compose.volume=collector-$target" \
      "hub_collector-$target" >/dev/null
    docker ps -q --filter label=com.docker.compose.project=hub \
      --filter "label=com.docker.compose.service=collector-$old" | xargs -r docker stop >/dev/null
    docker run --rm --user 0:0 --entrypoint sh \
      -v "hub_collector-$old:/from:ro" -v "hub_collector-$target:/to" "hub-collector:$TAG" -c \
      'test -e "/to/.from-$0" || { cp -an /from/. /to/ && touch "/to/.from-$0"; }
       chown 10001:10001 /to && chmod 0700 /to' "$old"
    echo "volume collector-$old recopié dans collector-$target"
  done
}

rollback() {
  say "RETOUR ARRIÈRE : $1"
  compose "$TAG" stop api importer scheduler litestream web 2>/dev/null || true
  if [ "$first_deploy" = 0 ]; then
    once "${PREV:-$TAG}" hub restore "$STAMP"
  fi
  if [ -n "$PREV" ]; then
    compose "$PREV" up -d --remove-orphans
    echo "revenu à l'image $PREV"
  fi
  exit 1
}

say "Migrations"
once "$TAG" hub db upgrade || rollback "migration en échec"

say "Vérification après migration"
once "$TAG" hub verify || rollback "verify échoue après migration"

if [ -n "${HUB_COLLECTOR_SECRETS:-}" ]; then
  say "Connexions des collecteurs (reprise des anciens fichiers, jetons des deux services)"
  # sans effet une fois faite : une connexion qui a ses secrets les garde, un fichier existant reste
  mkdir -p "$HUB_COLLECTOR_SECRETS"
  compose "$TAG" run --rm --no-deps -v "$HUB_COLLECTOR_SECRETS:/import" scheduler \
    hub connections import /import || rollback "reprise des connexions en échec"
  merge_collector_volumes
fi

say "Démarrage"
# COMPOSE_PROFILES=collectors dans deploy/.env : les collecteurs suivent la même image
compose "$TAG" up -d --remove-orphans

say "Contrôle de santé (30 s)"
healthy=0
for _ in $(seq 1 15); do
  if [ -n "${HUB_PUBLIC_ORIGIN:-}" ] && curl -fsS --max-time 2 "$HUB_PUBLIC_ORIGIN/api/health" >/dev/null 2>&1; then
    healthy=1; break
  fi
  # avant le premier enregistrement Tailscale, on vérifie au moins la chaîne web → api
  if [ -z "${HUB_STRICT_TAILSCALE:-}" ] && compose "$TAG" exec -T web wget -qO- http://127.0.0.1:8080/api/health >/dev/null 2>&1; then
    healthy=1; break
  fi
  sleep 2
done
[ "$healthy" = 1 ] || rollback "/api/health ne répond pas"

echo "$TAG" > "$STATE"
say "Déployé : $TAG (précédent : ${PREV:-aucun})"

if [ "$first_deploy" = 1 ]; then
  say "Première passkey : ouvre ${HUB_PUBLIC_ORIGIN:-l'app} et saisis ce code"
  once "$TAG" hub auth bootstrap-code || true
fi
