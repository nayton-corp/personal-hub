#!/usr/bin/env bash
# Migration depuis la version précédente (chantier S13) : la dernière version taguée crée ses
# bases et y importe un relevé fictif, puis le code courant les migre et les vérifie. C'est le
# chemin de chaque « make deploy », qui part toujours des bases de la version en place.
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
IBAN=CH9300762011623852957  # IBAN fictif des fabriques de test

prev() { (cd "$WORK/prev" && uv run --frozen --quiet "$@"); }
say() { printf '\n==> %s\n' "$*"; }

say "Version précédente $PREV : bases, compte et relevé fictifs"
prev python -c 'import pyrage; print(pyrage.x25519.Identity.generate())' > "$WORK/age.key"
chmod 0400 "$WORK/age.key"
prev hub db upgrade
prev python - "$WORK/history/2026-01.xml" <<'PY'
import sys
from datetime import date
from decimal import Decimal

sys.path.insert(0, ".")
from tests.factories.camt import Stmt, Tx, camt053

txs = [Tx("12.50", True, date(2026, 1, d)) for d in range(2, 9)]
txs.append(Tx("3000.00", False, date(2026, 1, 25), counterparty="Employeur Fictif SA", label="Salaire"))
with open(sys.argv[1], "wb") as f:
    f.write(camt053(Stmt(Decimal("1000"), date(2026, 1, 1), txs)))
PY
prev hub finance accounts add "Compte fictif" --iban "$IBAN" --budget
prev hub finance import-history "$WORK/history"
prev hub verify

say "Version courante : migration puis vérifications"
uv run --frozen --quiet hub db upgrade
uv run --frozen --quiet hub verify
uv run --frozen --quiet hub finance verify-ledger
echo "migration depuis $PREV : ok"
