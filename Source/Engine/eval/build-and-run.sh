#!/bin/bash
# 階段一 baseline harness:編譯並對真實辭典跑 unigram 引擎 top-1 選錯率。
# 可重複執行;rescorer(階段二)前後各跑一次,比較選錯率。
set -euo pipefail

ENGINE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DATA="$ENGINE_DIR/../Data/data.txt"
BIN="${TMPDIR:-/tmp}/rerank_eval"

clang++ -std=c++17 -O2 -I"$ENGINE_DIR" -I"$ENGINE_DIR/gramambular2" \
  "$ENGINE_DIR/eval/rerank_eval.cpp" \
  "$ENGINE_DIR/gramambular2/reading_grid.cpp" \
  "$ENGINE_DIR/ParselessLM.cpp" \
  "$ENGINE_DIR/ParselessPhraseDB.cpp" \
  "$ENGINE_DIR/MemoryMappedFile.cpp" \
  -o "$BIN"

"$BIN" "$DATA"
