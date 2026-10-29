#!/usr/bin/env bash
# Instance d'essai (chantier S13) : l'image d'une version rejoue ses contrôles sur des données
# fictives, sans toucher au hub en place, avant le « oui déploie ».
#   deploy/trial.sh <tag> [tag-précédent]   (défaut : deploy/.current-tag)
# 1. la version précédente crée les bases et importe un an de relevés fictifs (deux comptes) ;
# 2. la nouvelle migre, vérifie (`hub verify`, `verify-ledger`) et répond sur /api/health.
# Sans version précédente, la nouvelle fait tout. Volumes jetables, aucun port publié, ni secret
# ni dossier du Mac : seul scripts/demo_data.py est monté, en lecture.
set -euo pipefail

TAG="${1:?usage: deploy/trial.sh <tag> [tag-précédent]}"
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
PREV="${2:-$(cat "$HERE/.current-tag" 2>/dev/null || true)}"
PREV="${PREV:-$TAG}"
NAME="hub-essai-$$"
PLATFORM="${HUB_PLATFORM:-linux/arm64}"
VOLS=("$NAME-data" "$NAME-archive" "$NAME-inbox")
say() { printf '\n==> %s\n' "$*"; }

cleanup() {
  docker rm -f "$NAME-api" >/dev/null 2>&1 || true
  docker volume rm "${VOLS[@]}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

# les volumes neufs prennent le propriétaire (10001) des dossiers de l'image
run() {
  local image="$1"; shift
  docker run --rm --platform "$PLATFORM" --network none \
    -v "$NAME-data:/srv/hub/data" -v "$NAME-archive:/srv/hub/archive" \
    -v "$NAME-inbox:/srv/hub/inbox" -v "$ROOT/scripts/demo_data.py:/opt/demo_data.py:ro" \
    -e HUB_SECRETS__AGE_KEY_FILE=/srv/hub/data/age.key "$image" "$@"
}

for image in "hub:$PREV" "hub:$TAG"; do
  docker image inspect "$image" >/dev/null 2>&1 || { echo "image $image absente (make deploy la tire ou la construit)"; exit 1; }
done

say "Version $PREV : bases, comptes et un an de relevés fictifs"
run "hub:$PREV" sh -c '
  set -e
  python -c "import pyrage; print(pyrage.x25519.Identity.generate())" > /srv/hub/data/age.key
  chmod 0400 /srv/hub/data/age.key
  hub db upgrade
  python /opt/demo_data.py /srv/hub/inbox/demo
  while IFS="$(printf "\t")" read -r iban name options; do
    hub finance accounts add "$name" --iban "$iban" $options
  done < /srv/hub/inbox/demo/accounts.tsv
  hub finance import-history /srv/hub/inbox/demo'

say "Version $TAG : migration et vérifications"
run "hub:$TAG" sh -c 'hub db upgrade && hub verify && hub finance verify-ledger'

say "Version $TAG : l'API démarre et répond"
docker run -d --platform "$PLATFORM" --name "$NAME-api" --network none \
  -v "$NAME-data:/srv/hub/data" -v "$NAME-archive:/srv/hub/archive" -v "$NAME-inbox:/srv/hub/inbox" \
  -e HUB_SECRETS__AGE_KEY_FILE=/srv/hub/data/age.key "hub:$TAG" >/dev/null
for _ in $(seq 1 60); do  # sous QEMU (CI), le démarrage prend du temps
  if docker exec "$NAME-api" python -c '
import json, urllib.request
h = json.load(urllib.request.urlopen("http://127.0.0.1:8710/api/health", timeout=2))
print(h["status"], "v" + h["version"])
assert h["status"] == "ok"' 2>/dev/null; then
    echo "instance d'essai $TAG : ok (depuis $PREV)"
    exit 0
  fi
  sleep 1
done
docker logs --tail 30 "$NAME-api" >&2
echo "instance d'essai $TAG : /api/health ne répond pas" >&2
exit 1
