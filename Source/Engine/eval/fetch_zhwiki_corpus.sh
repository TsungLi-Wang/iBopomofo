#!/bin/bash
# Download the latest Chinese Wikipedia article dump for rescorer experiments.
#
# The dump is large and is intentionally written under eval/corpus/, which is
# ignored by git. Use train_char_ngram.py with --max-text-chars for quick
# experiments before training on the full dump.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
OUT_DIR="$SCRIPT_DIR/corpus"
URL="${1:-https://dumps.wikimedia.org/zhwiki/latest/zhwiki-latest-pages-articles.xml.bz2}"
OUT="$OUT_DIR/$(basename "$URL")"

mkdir -p "$OUT_DIR"

if command -v curl >/dev/null 2>&1; then
  curl -L --continue-at - --output "$OUT" "$URL"
elif command -v wget >/dev/null 2>&1; then
  wget -c -O "$OUT" "$URL"
else
  echo "curl or wget is required" >&2
  exit 2
fi

echo "$OUT"
