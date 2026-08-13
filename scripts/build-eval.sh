#!/bin/bash
# 建置新北極星評分機（newstar_homophone_eval）到 repo 內的固定路徑。
#
# ## 為什麼要有這支
#
# 2026-08-12：`ship-gate.sh` 的評分機原本預設在 `/tmp/newstar_homophone_eval`。
# macOS 重開機清 /tmp → 出貨硬關卡直接跑不起來（`SHIP_GATE_STATUS=FAIL`），
# 而且同一天發現有三樣「重要東西」都住在 /tmp，全部隨重開機蒸發。
#
# 輸出改到 `bin/`（不是 `build/` —— `clean-build-dirs.sh` 會把整個 build/
# `rm -rf` 掉，放那裡只是換一種方式蒸發）。`bin/` 已在 .gitignore，不會進 git。
#
# 用法：
#   ./scripts/build-eval.sh                       # → bin/newstar_homophone_eval
#   IBOPOMOFO_EVAL_BIN=/path/to/out ./scripts/build-eval.sh
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"

EVAL_OUT="${IBOPOMOFO_EVAL_BIN:-$ROOT/bin/newstar_homophone_eval}"
case "$EVAL_OUT" in
  /*) ;;
  *) EVAL_OUT="$ROOT/$EVAL_OUT" ;;
esac
mkdir -p "$(dirname "$EVAL_OUT")"

cd Source/Engine/eval/benchmarks
ENGINE=../..

echo "編譯評分機 → $EVAL_OUT"
clang++ -std=c++17 -O2 \
  -I"$ENGINE" -I"$ENGINE/gramambular2" \
  newstar_homophone_eval.cpp \
  "$ENGINE/gramambular2/reading_grid.cpp" \
  "$ENGINE/CorpusBigramContextModel.cpp" \
  "$ENGINE/NeuralLMPathScorer.cpp" \
  "$ENGINE/ParselessLM.cpp" \
  "$ENGINE/ParselessPhraseDB.cpp" \
  "$ENGINE/MemoryMappedFile.cpp" \
  "$ENGINE/ParticleRuleDisambiguator.cpp" \
  -framework Accelerate \
  -o "$EVAL_OUT"

echo "完成：$EVAL_OUT"
ls -l "$EVAL_OUT"

# 可選：ORACLE=1 順便建 oracle_ceiling（錯誤分層地圖用；預設不建，
# 不影響上面的產物路徑與既有呼叫端）。
if [ "${ORACLE:-0}" = "1" ]; then
  ORACLE_OUT="$ROOT/bin/oracle_ceiling"
  echo "編譯 oracle_ceiling → $ORACLE_OUT"
  clang++ -std=c++17 -O2 \
    -I"$ENGINE" -I"$ENGINE/gramambular2" \
    oracle_ceiling.cpp \
    "$ENGINE/gramambular2/reading_grid.cpp" \
    "$ENGINE/CorpusBigramContextModel.cpp" \
    "$ENGINE/NeuralLMPathScorer.cpp" \
    "$ENGINE/ParselessLM.cpp" \
    "$ENGINE/ParselessPhraseDB.cpp" \
    "$ENGINE/MemoryMappedFile.cpp" \
    -framework Accelerate \
    -o "$ORACLE_OUT"
  echo "完成：$ORACLE_OUT"
fi
