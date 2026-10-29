#!/usr/bin/env bash
# Première installation (docs/exploitation/installation.md) : `make init`.
# Construit l'image du hub, puis lance `hub init` dans un conteneur jetable : clé age, secrets
# chiffrés, dossiers et deploy/.env. Seul Docker est requis sur la machine ; rien de ce qui existe
# n'est remplacé. Réglages par variables ou par questions :
#   HUB_CONFIG (~/.config/hub), HUB_HOME (~/PersonalHub), HUB_TZ (fuseau de la machine),
#   HUB_CURRENCY (CHF), HUB_COUNTRY (CH), HUB_PUBLIC_ORIGIN (https://hub.<tailnet>.ts.net)
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
PLATFORM="${HUB_PLATFORM:-linux/arm64}"

ask() {  # ask <variable> <question> <défaut>
  local value="${!1:-}"
  if [ -z "$value" ] && [ -t 0 ]; then read -r -p "$2 [$3] : " value; fi
  printf -v "$1" '%s' "${value:-$3}"
}

host_tz="$(readlink /etc/localtime 2>/dev/null | sed 's#.*/zoneinfo/##')"
ask HUB_CONFIG "Dossier de la clé et des secrets" "$HOME/.config/hub"
ask HUB_HOME "Dossier des exports et des sauvegardes" "$HOME/PersonalHub"
ask HUB_TZ "Fuseau" "${host_tz:-Europe/Zurich}"
ask HUB_COUNTRY "Pays (ISO, deux lettres)" "CH"
ask HUB_CURRENCY "Devise de base (ne change plus ensuite)" "CHF"
# le nœud Tailscale s'appelle « hub » : son adresse se déduit du nom du tailnet (console → DNS)
ask HUB_PUBLIC_ORIGIN "Adresse du hub, https://hub.<tailnet>.ts.net" "https://hub.votre-tailnet.ts.net"

# créés ici, avec l'utilisateur courant : un dossier monté absent serait créé par Docker
mkdir -p "$HUB_CONFIG" "$HUB_HOME"
chmod 700 "$HUB_CONFIG"

docker build --platform "$PLATFORM" --target hub -t hub:init "$ROOT"
docker run --rm --platform "$PLATFORM" --user "$(id -u):$(id -g)" --read-only --tmpfs /tmp \
  -e HOME=/tmp -v "$HUB_CONFIG:$HUB_CONFIG" -v "$HUB_HOME:$HUB_HOME" -v "$HERE:$HERE" \
  hub:init hub init --config "$HUB_CONFIG" --home "$HUB_HOME" \
  --env "$HERE/.env" --template "$HERE/.env.example" --origin "$HUB_PUBLIC_ORIGIN" \
  --tz "$HUB_TZ" --currency "$HUB_CURRENCY" --country "$HUB_COUNTRY"

cat <<TXT

Suite (docs/exploitation/installation.md) :
  1. Copie dans ton kit de secours $HUB_CONFIG/age.key et secrets.enc.yaml : la clé seule
     rouvre les secrets (mot de passe restic) et les sauvegardes.
  2. Dans deploy/.env : TS_AUTHKEY (clé Tailscale à usage unique, tag:hub).
  3. make deploy TAG=v1 : le premier déploiement affiche le code d'inscription de la passkey.
TXT
