#!/bin/sh
# Installe SearXNG dans ~/Domia/searxng (son code et son venv), hors du dépôt Domia. Relancer pour le mettre à jour.
set -eu
DIR="$HOME/Domia/searxng"
if [ -d "$DIR/src/.git" ]; then
  git -C "$DIR/src" pull --ff-only
else
  mkdir -p "$DIR"
  git clone --depth 1 https://github.com/searxng/searxng "$DIR/src"
fi
[ -x "$DIR/.venv/bin/python" ] || python3.12 -m venv "$DIR/.venv"
"$DIR/.venv/bin/pip" install -q -U pip setuptools wheel pyyaml
"$DIR/.venv/bin/pip" install -q -r "$DIR/src/requirements.txt"
(cd "$DIR/src" && "$DIR/.venv/bin/pip" install -q --no-build-isolation -e .)
echo "SearXNG installé : $DIR"
