#!/usr/bin/env bash
# Copies the latin, non-variable woff2 files zy.css references out of the installed
# @fontsource packages into static/fonts. Filenames match zy.css's @font-face src, so
# this is the only thing that needs to change if a weight or family is added there.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

SRC=node_modules/@fontsource
DEST=src/ansibleinventorycmdb/static/fonts
mkdir -p "$DEST"

for weight in 400 500 600 700; do
  cp "$SRC/fira-code/files/fira-code-latin-$weight-normal.woff2" "$DEST/fira-code-$weight.woff2"
done

for weight in 400 500; do
  cp "$SRC/noto-sans-display/files/noto-sans-display-latin-$weight-normal.woff2" \
     "$DEST/noto-sans-display-latin-$weight.woff2"
  cp "$SRC/noto-sans-display/files/noto-sans-display-latin-$weight-italic.woff2" \
     "$DEST/noto-sans-display-latin-${weight}italic.woff2"
done

# 600 normal only: it exists to give <b> a real face instead of a synthesised one, and nothing is bold italic.
cp "$SRC/noto-sans-display/files/noto-sans-display-latin-600-normal.woff2" \
   "$DEST/noto-sans-display-latin-600.woff2"
