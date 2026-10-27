#!/usr/bin/env bash
# Refuse tout fichier qui pourrait contenir des données réelles : relevés, bases, exports.
# Sans argument : vérifie tous les fichiers suivis (CI). Avec arguments : ces fichiers (pre-commit).
set -euo pipefail
if [ "$#" -gt 0 ]; then files=("$@"); else mapfile -t files < <(git ls-files); fi
bad=0
for f in "${files[@]}"; do
  case "$f" in
    tests/fixtures/generated/*) continue ;;  # produits par les fabriques, jamais commités
  esac
  case "$f" in
    *.xml|*.XML|*.pdf|*.PDF|*.db|*.db-wal|*.db-shm|*.sqlite|*.sqlite3|*.csv|*.CSV|*.xlsx|*.xls|\
    *.ofx|*.qif|*.mt940|*.sta|*.camt|*.zip|*.age|data/*|*/data/*|inbox/*|*/inbox/*|archive/*|\
    *.key|*secrets*.yaml|.env|*/.env)
      echo "refusé (données ou secret possible) : $f" >&2; bad=1 ;;
  esac
done
exit "$bad"
