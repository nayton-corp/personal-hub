#!/usr/bin/env bash
# Reprend le contrat avec Domia (assistant/domia_assistant/contract/) depuis un clone de Domia :
# réponses de référence de l'API, référence de la configuration, maison du banc. Les prénoms du
# foyer cités en exemple deviennent ceux des tests (aucun nom réel dans le dépôt).
set -euo pipefail
src="${1:?usage : scripts/domia_contract.sh CHEMIN_DU_CLONE_DE_DOMIA}"
dst="$(cd "$(dirname "$0")/.." && pwd)/assistant/domia_assistant/contract"
mkdir -p "$dst/api"
cp "$src"/backend/src/test/resources/api/* "$dst/api/"
cp "$src/docs/config-reference.md" "$src/seeds/seed-local.yaml" "$dst/"
grep -rlIi "nathan" "$dst" | xargs -r sed -i.bak 's/Nathan/Robin/g; s/nathan/robin/g'
find "$dst" -name '*.bak' -delete
printf '%s %s\n' "$(git -C "$src" describe --tags --always)" "$(git -C "$src" rev-parse HEAD)" \
  > "$dst/DOMIA_VERSION"
echo "contrat repris de Domia $(cat "$dst/DOMIA_VERSION")"
