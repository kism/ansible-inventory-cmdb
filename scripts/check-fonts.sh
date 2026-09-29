#!/usr/bin/env bash
# Every woff2 zy.css references must exist and actually be a woff2. Catches the one failure mode here: adding a
# weight to zy.css, or bumping a @fontsource package, without re-running `npm run fonts` (scripts/fetch-fonts.sh).
# The rules are read off the stylesheet, so adding a weight needs no change in this file.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

STATIC=src/ansibleinventorycmdb/static

fonts=$(grep -o 'url("/static/[^"]*\.woff2")' "$STATIC/zy.css" | sed 's|url("/static/||; s|")$||' | sort -u)
if [ -z "$fonts" ]; then
  echo "No woff2 urls found in $STATIC/zy.css, so this check proves nothing" >&2
  exit 1
fi

status=0
while read -r font; do
  # wOF2 is the woff2 magic number, so a truncated, empty or wrong-format file fails here too.
  if [ "$(head -c4 "$STATIC/$font" 2>/dev/null)" = "wOF2" ]; then
    echo "[OK] $font"
  else
    echo "[FAILED] $font is missing or is not a woff2"
    status=1
  fi
done <<<"$fonts"

exit $status
