#!/bin/bash
# node-scorer-parity.sh — 換節點層模型的第一道關卡：C++ 與 PyTorch 逐題同分。
#
# ## 為什麼要有這支
#
# 匯出格式錯一個位元組（閘序、row-major、GELU 版本、右文有沒有反序…），
# C++ 端照樣「載得起來、分數看起來合理」，然後所有 A/B 數字都是假的。
# 這種錯不會報錯 —— 只會讓人花半天去怪模型。
#
# 動手順序（AI_HANDOFF_PROMPT「工作方式」那四步）的第一步是
# 「我要用什麼證據判斷這東西有效」。對換模型來說，那份證據的前提就是這支：
# **兩邊不同分，後面所有數字都不必看。**
#
# 用法：
#   ./scripts/node-scorer-parity.sh <model.bin> <資料目錄> <ckpt.pt> [venv/bin/python]
set -uo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"

MODEL="${1:-}"
DATA="${2:-}"
CKPT="${3:-}"
PY="${4:-python3}"
if [ -z "$MODEL" ] || [ -z "$DATA" ] || [ -z "$CKPT" ]; then
    sed -n '2,20p' "$0"
    exit 2
fi

PROBE="$ROOT/bin/node_scorer_probe"
if [ ! -x "$PROBE" ]; then
    echo "probe 不存在 —— 先建置：NODE_PROBE=1 ./scripts/build-eval.sh"
    NODE_PROBE=1 ./scripts/build-eval.sh || exit 1
fi

exec "$PY" Source/Engine/eval/check_node_scorer_parity.py \
    --probe "$PROBE" --model "$MODEL" --data "$DATA" --ckpt "$CKPT"
