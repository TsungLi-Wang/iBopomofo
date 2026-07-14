#!/bin/bash
# Compile and run the Taiwan Typing Benchmark (north-star metric).
#
# baseline (unigram-only) is always printed. If a bigram PMI table is given,
# a lambda grid search is run and before/after accuracy is printed.
#
# Usage:
#   build-and-run.sh [sentences.tsv] [bigram-pmi.tsv] [single-lambda]
set -euo pipefail

BENCH_DIR="$(cd "$(dirname "$0")" && pwd)"
ENGINE_DIR="$(cd "$BENCH_DIR/../.." && pwd)"
DATA="$ENGINE_DIR/../Data/data.txt"
# North-star default: tw538 (PTT lifestyle boards, human-reviewed).
# Historical 395 set remains at tw-sentences.tsv for archive comparisons.
CASES="${1:-$BENCH_DIR/tw538-northstar.tsv}"
BIGRAM="${2:-}"
LAMBDA="${3:-}"
BIN="${TMPDIR:-/tmp}/tw_benchmark"

clang++ -std=c++17 -O2 -I"$ENGINE_DIR" -I"$ENGINE_DIR/gramambular2" \
  "$BENCH_DIR/tw_benchmark.cpp" \
  "$ENGINE_DIR/gramambular2/reading_grid.cpp" \
  "$ENGINE_DIR/CorpusBigramContextModel.cpp" \
  "$ENGINE_DIR/ParselessLM.cpp" \
  "$ENGINE_DIR/ParselessPhraseDB.cpp" \
  "$ENGINE_DIR/MemoryMappedFile.cpp" \
  -o "$BIN"

"$BIN" "$CASES" "$DATA" "$BIGRAM" "$LAMBDA"
