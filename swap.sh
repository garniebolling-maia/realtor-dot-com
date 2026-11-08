#!/usr/bin/env bash
# Switch the LIVE payload served at /v1/listings/ between baseline (v1) and drifted (v2).
# One-time setup:
#   python3 generate_pages.py --base-url $BASE --version 1 --out-dir snapshots/v1
#   python3 generate_pages.py --base-url $BASE --version 2 --out-dir snapshots/v2
# Usage: ./swap.sh v1   |   ./swap.sh v2
set -euo pipefail
VER="${1:-}"
if [[ "$VER" != "v1" && "$VER" != "v2" ]]; then echo "Usage: ./swap.sh v1|v2"; exit 1; fi
[[ -d "snapshots/$VER" ]] || { echo "snapshots/$VER missing - run generate_pages.py first"; exit 1; }
mkdir -p v1/listings
rm -f v1/listings/page-*.json
cp snapshots/"$VER"/page-*.json v1/listings/
git add -A
git commit -m "MLS API live payload -> $VER" || echo "Nothing changed"
git push
echo "Live payload now $VER. Allow ~1-5 min for GitHub Pages to update."
