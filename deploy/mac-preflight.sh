#!/usr/bin/env bash
# Contrôles de la phase 1 sur le Mac (ticket L0-07). Ne modifie rien ; échoue au premier
# point bloquant. À lancer avant chaque déploiement (make deploy le fait).
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
fail=0
ok()   { printf '  ok      %s\n' "$*"; }
warn() { printf '  attention %s\n' "$*"; }
ko()   { printf '  ÉCHEC   %s\n' "$*"; fail=1; }

[ -f "$HERE/.env" ] || { echo "deploy/.env manquant (copier deploy/.env.example)"; exit 1; }
# shellcheck disable=SC1091
set -a; . "$HERE/.env"; set +a

echo "Chiffrement et veille"
if command -v fdesetup >/dev/null; then
  fdesetup status | grep -q "FileVault is On" && ok "FileVault actif" || ko "FileVault inactif"
  sleep_ac="$(pmset -g custom 2>/dev/null | awk '/AC Power/{f=1} f && $1=="sleep"{print $2; exit}')"
  [ "$sleep_ac" = "0" ] && ok "pas de veille sur secteur" \
    || ko "veille sur secteur = ${sleep_ac:-?} (sudo pmset -c sleep 0)"
else
  warn "pas sur macOS : FileVault et pmset non vérifiés"
fi

echo "Moteur de conteneurs"
docker info >/dev/null 2>&1 && ok "docker répond ($(docker context show 2>/dev/null))" \
  || ko "docker ne répond pas (OrbStack lancé ?)"

echo "Clé et secrets"
if [ -f "${HUB_AGE_KEY:-}" ]; then
  perm="$(stat -f %Lp "$HUB_AGE_KEY" 2>/dev/null || stat -c %a "$HUB_AGE_KEY")"
  [ "$perm" = "400" ] && ok "clé age en 0400" || ko "clé age en $perm (chmod 400)"
else
  ko "clé age absente : $HUB_AGE_KEY"
fi
[ -f "${HUB_SECRETS:-}" ] && ok "secrets chiffrés présents" || ko "secrets absents : $HUB_SECRETS"

echo "Dossiers montés"
for d in HUB_INBOX HUB_REPLICA HUB_RESTIC_LOCAL; do
  [ -d "${!d:-}" ] && ok "$d = ${!d}" || ko "$d n'existe pas : ${!d:-}"
done
# aucune base SQLite active ne doit vivre dans un dossier du Mac monté dans un conteneur
if [ -d "${HUB_INBOX:-}" ] && find "$HUB_INBOX" -name '*.db' -o -name '*.db-wal' | grep -q .; then
  ko "une base SQLite traîne dans la boîte d'entrée"
else
  ok "aucune base dans les dossiers montés"
fi

echo "Réseau"
if docker compose --project-directory "$HERE" -f "$HERE/compose.yaml" --env-file "$HERE/.env" \
     config --format json 2>/dev/null | grep -q '"published"'; then
  ko "un port est publié sur le Mac : l'app ne doit être joignable que par Tailscale"
else
  ok "aucun port publié"
fi
case "${HUB_PUBLIC_ORIGIN:-}" in
  https://*.ts.net) ok "origine $HUB_PUBLIC_ORIGIN" ;;
  *) warn "HUB_PUBLIC_ORIGIN n'est pas une adresse *.ts.net : les passkeys en dépendent" ;;
esac

[ "$fail" = 0 ] && echo "Prêt." || echo "Corriger les points en échec avant de déployer."
exit "$fail"
