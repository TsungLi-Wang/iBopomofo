#!/bin/bash
# Evaluate a path-char-lstm.bin on tw538 with nbest_path_rerank harness.
# Usage: eval_spoken_lstm.sh <path-char-lstm.bin> [label]
set -euo pipefail
BENCH_DIR="$(cd "$(dirname "$0")" && pwd)"
ENGINE_DIR="$(cd "$BENCH_DIR/../.." && pwd)"
WEIGHT="${1:?weight bin required}"
LABEL="${2:-eval}"
BIN="/tmp/nbest_neural_${LABEL}"
DATA="$ENGINE_DIR/../Data/data.txt"
CASES="$BENCH_DIR/tw538-northstar.tsv"
BIGRAM="$ENGINE_DIR/../Data/word-bigrams.tsv"

clang++ -std=c++17 -O2 -I"$ENGINE_DIR" -I"$ENGINE_DIR/gramambular2" \
  "$BENCH_DIR/nbest_path_rerank.cpp" \
  "$ENGINE_DIR/gramambular2/reading_grid.cpp" \
  "$ENGINE_DIR/CorpusBigramContextModel.cpp" \
  "$ENGINE_DIR/ParselessLM.cpp" \
  "$ENGINE_DIR/ParselessPhraseDB.cpp" \
  "$ENGINE_DIR/MemoryMappedFile.cpp" \
  "$ENGINE_DIR/NeuralLMPathScorer.cpp" \
  -o "$BIN"

# ν grid 0.25 0.5 0.75 (and 0 for baseline ON) via default if we pass empty? harness takes single nu or full grid.
# Run full default grid (0,0.1,0.25,0.5,0.75,1.0) when nu omitted — but argv requires path.
# Pass three separate runs for clear TABLE lines + one full grid.
OUT_DIR="$ENGINE_DIR/eval/analysis"
mkdir -p "$OUT_DIR"
LOG="$OUT_DIR/tw538-lstm-${LABEL}.stdout.txt"

{
  echo "LABEL=$LABEL WEIGHT=$WEIGHT"
  shasum -a 256 "$WEIGHT"
  "$BIN" "$CASES" "$DATA" "$BIGRAM" 0.75 "$WEIGHT"
} 2>&1 | tee "$LOG"

echo "LOG=$LOG"
