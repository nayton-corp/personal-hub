#!/usr/bin/env bash
# Migration depuis la version précédente (chantier S13) : la dernière version taguée crée ses
# bases et y importe un an de relevés fictifs (scripts/demo_data.py), puis le code courant les
# migre et les vérifie. C'est le chemin de chaque « make deploy », qui part toujours des bases
# de la version en place.
#   scripts/upgrade_from_previous.sh [ref]   (défaut : dernier tag vX.Y.Z avant HEAD)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PREV="${1:-$(git describe --tags --abbrev=0 --match 'v[0-9]*.[0-9]*.[0-9]*' HEAD^ 2>/dev/null || true)}"
if [ -z "$PREV" ]; then
  echo "aucune version taguée avant HEAD : rien à migrer"
  exit 0
fi

WORK="$(mktemp -d)"
cleanup() { git worktree remove --force "$WORK/prev" 2>/dev/null || true; rm -rf "${WORK:?}"; }
trap cleanup EXIT
git worktree add --detach --quiet "$WORK/prev" "$PREV"

mkdir -p "$WORK/var/data" "$WORK/var/inbox" "$WORK/var/archive" "$WORK/var/backup" "$WORK/history"
export HUB_PATHS__DATA="$WORK/var/data" HUB_PATHS__INBOX="$WORK/var/inbox" \
  HUB_PATHS__ARCHIVE="$WORK/var/archive" HUB_PATHS__BACKUP="$WORK/var/backup" \
  HUB_SECRETS__AGE_KEY_FILE="$WORK/age.key"

prev() { (cd "$WORK/prev" && uv run --frozen --quiet "$@"); }
say() { printf '\n==> %s\n' "$*"; }

say "Version précédente $PREV : bases, comptes et un an de relevés fictifs"
prev python -c 'import pyrage; print(pyrage.x25519.Identity.generate())' > "$WORK/age.key"
chmod 0400 "$WORK/age.key"
prev hub db upgrade
python3 "$ROOT/scripts/demo_data.py" "$WORK/history"
while IFS=$'\t' read -r iban name options; do
  # shellcheck disable=SC2086 # options de la ligne : plusieurs mots
  prev hub finance accounts add "$name" --iban "$iban" $options
done < "$WORK/history/accounts.tsv"
prev hub finance import-history "$WORK/history"
prev hub verify

say "Version courante : migration puis vérifications"
uv run --frozen --quiet hub db upgrade
uv run --frozen --quiet hub verify
uv run --frozen --quiet hub finance verify-ledger
echo "migration depuis $PREV : ok"
