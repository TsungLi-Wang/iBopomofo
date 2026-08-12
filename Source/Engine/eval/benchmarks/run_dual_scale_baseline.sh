#!/bin/bash
# Run shipping baseline on MAIN_SCALE + EX1166 (reference).
# Requires: /tmp/newstar_homophone_eval (see README-newstar.md)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../../.." && pwd)"
EVAL="${IBOPOMOFO_EVAL_BIN:-${EVAL:-/tmp/newstar_homophone_eval}}"
OUT="${OUT:-$HOME/laowang-data/main-scale}"
MAIN="${MAIN:-$OUT/MAIN_SCALE.jsonl}"
CORPUS_DIR="${IBOPOMOFO_CORPUS_DIR:-$HOME/Documents/i注音-語料/EX1166-題庫}"
EX="${EX:-$CORPUS_DIR/EX1166-全部.jsonl}"
BIN="$ROOT/Source/Data/path-char-lstm.bin"
RULES="$ROOT/Source/Data/particle-rules.tsv"

[ -x "$EVAL" ] || { echo "missing $EVAL — rebuild per README-newstar.md"; exit 1; }
[ -f "$MAIN" ] || { echo "missing $MAIN — run main_scale_dedup.py first"; exit 1; }

mkdir -p "$OUT"
echo "=== MAIN $MAIN ==="
"$EVAL" "$MAIN" \
  "$ROOT/Source/Data/data.txt" \
  "$ROOT/Source/Data/word-bigrams.tsv" \
  "$BIN" shipping 0.75 0.75 \
  "" "$OUT/MAIN-baseline.dump.tsv" \
  "$RULES" | tee "$OUT/MAIN-baseline.stdout.txt"

echo "=== EX1166 (REFERENCE) $EX ==="
"$EVAL" "$EX" \
  "$ROOT/Source/Data/data.txt" \
  "$ROOT/Source/Data/word-bigrams.tsv" \
  "$BIN" shipping 0.75 0.75 \
  "" "$OUT/EX1166-baseline.dump.tsv" \
  "$RULES" | tee "$OUT/EX1166-baseline.stdout.txt"

echo "done. dumps under $OUT"
