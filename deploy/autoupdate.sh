#!/usr/bin/env bash
# Mise à jour seule du hub sur le Pi (D-026) : la fusion de la PR de version est le seul geste.
#   deploy/autoupdate.sh            (le minuteur hub-autoupdate le lance toutes les 5 min)
# 1. lit la dernière release GitHub (créée seulement une fois les images publiées et analysées) ;
# 2. rien à faire si c'est la version en place, une version plus ancienne, ou celle qui vient
#    d'échouer ; 3. place le clone sur le tag et lance deploy/deploy.sh (essai, verify, copie
#    des bases, migrations, retour arrière seul au moindre échec) ; 4. une notification ntfy
#    dit ce qui tourne. Un échec n'est pas retenté : seule une version plus récente relance
#    (ou `rm deploy/.failed-tag`). Journal de chaque essai : deploy/logs/. Les chiffres de la
#    finance sont figés avant (`hub finance golden save`) et recomptés après (`golden check`) :
#    un écart est signalé, sans retour arrière (il peut être annoncé dans le CHANGELOG).
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
STATE="$HERE/.current-tag"
FAILED="$HERE/.failed-tag"
LOGS="$HERE/logs"
REPO="${HUB_GITHUB_REPO:-nayton-corp/personal-hub}"
SEMVER='^v[0-9]+\.[0-9]+\.[0-9]+$'

[ -f "$HERE/.env" ] || { echo "deploy/.env manquant"; exit 1; }
# shellcheck disable=SC1091
set -a; . "$HERE/.env"; set +a

# un seul passage à la fois : un déploiement long ne se double pas au tour suivant du minuteur
exec 9>"$HERE/.autoupdate.lock"
flock -n 9 || exit 0

# une commande hub dans un conteneur jetable de l'image <tag>
once() {
  HUB_TAG="$1" docker compose --project-directory "$HERE" -f "$HERE/compose.yaml" \
    --env-file "$HERE/.env" run --rm --no-deps -T scheduler "${@:2}"
}
# notification depuis l'image qui tourne : un texte générique, jamais un montant
notify() {
  once "$1" hub ops notify "${@:2}" >/dev/null 2>&1 || echo "(notification impossible)"
}

latest="$(curl -fsS --max-time 20 -H 'Accept: application/vnd.github+json' \
  "https://api.github.com/repos/$REPO/releases/latest" 2>/dev/null \
  | grep -o '"tag_name": *"[^"]*"' | head -1 | sed 's/.*"\([^"]*\)"$/\1/' || true)"
# réseau coupé, limite de l'API : on réessaie au tour suivant, sans bruit
[[ "$latest" =~ $SEMVER ]] || exit 0

current="$(cat "$STATE" 2>/dev/null || true)"
# la première installation et la bascule depuis le Mac se font à la main (docs/exploitation/pi.md)
[ -n "$current" ] || { echo "aucune version en place : premier déploiement à la main"; exit 0; }
[ "$latest" = "$current" ] && exit 0
[ "$latest" = "$(cat "$FAILED" 2>/dev/null || true)" ] && exit 0
if [ "$(printf '%s\n%s\n' "$current" "$latest" | sort -V | tail -1)" != "$latest" ]; then
  exit 0  # jamais en arrière tout seul : un retour se fait à la main (make deploy TAG=…)
fi

mkdir -p "$LOGS"
log="$LOGS/deploy-$latest-$(date +%Y%m%dT%H%M%S).log"
# les 20 derniers journaux suffisent
find "$LOGS" -name 'deploy-*.log' -type f | sort | head -n -20 | xargs -r rm -f
echo "mise à jour $current → $latest (journal : $log)"

fail() {
  echo "$latest" > "$FAILED"
  # le clone revient sur la version qui tourne : hubc lit le même compose.yaml qu'elle
  git -C "$ROOT" checkout --quiet --detach "$current" 2>/dev/null || true
  echo "ÉCHEC : $1"
  notify "$current" "Hub : $latest non installée" \
    "$1. La version $current tourne toujours. Journal sur le Pi : deploy/logs." --urgent
  exit 1
}

{ git -C "$ROOT" diff --quiet HEAD && git -C "$ROOT" diff --cached --quiet; } \
  || fail "le clone a des modifications locales"
git -C "$ROOT" fetch --quiet --tags --force origin || fail "git fetch impossible"
git -C "$ROOT" checkout --quiet --detach "$latest" || fail "tag $latest introuvable"

echo "étalon des chiffres ($current)" >"$log"
once "$current" hub finance golden save >>"$log" 2>&1 || echo "(étalon impossible)" >>"$log"

# le script lancé est celui du tag : une version peut changer sa façon de se déployer
if ! { "$HERE/mac-preflight.sh" && "$HERE/deploy.sh" "$latest"; } >>"$log" 2>&1; then
  why="$(grep -E 'RETOUR ARRIÈRE|arrêt|ÉCHEC' "$log" | tail -1 || true)"
  fail "le déploiement a échoué (${why:-$(tail -1 "$log")})"
fi

rm -f "$FAILED"
echo "déployé : $latest"
if once "$latest" hub finance golden check >>"$log" 2>&1; then
  notify "$latest" "Hub $latest installé" "Mise à jour faite (avant : $current). Chiffres identiques."
else
  notify "$latest" "Hub $latest installé, chiffres à regarder" \
    "Écart ou contrôle impossible après la mise à jour : hub finance golden check sur le Pi." --urgent
fi
