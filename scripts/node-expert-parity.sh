#!/bin/bash
# node-expert-parity.sh — 換節點層專家的**第一道關卡**：C++ 與 PyTorch 逐題同分。
#
# ## 為什麼這一關排在效果前面
#
# 匯出格式錯一個位元組（矩陣方向、GELU 版本、左右文補 PAD 的對齊、候選排序、
# 引擎分數縮放…），C++ 端照樣「載得起來、分數看起來合理」，然後所有 A/B 數字
# 都是假的。這種錯不會報錯，只會讓人花半天怪模型。
#
# 交班檔「動手順序」的第一步是「我要用什麼證據判斷這東西有效」。對換模型來說，
# 那份證據的前提就是這支：**兩邊不同分，後面什麼都不必看。**
#
# 它吃的是 node_sample_extract 產生的 nodes.tsv，所以驗到的是整條特徵管線，
# 不只是矩陣乘法。
#
# 用法：
#   ./scripts/node-expert-parity.sh <model.bin> <nodes.tsv> <ckpt.pt> [venv/bin/python]
set -uo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"

MODEL="${1:-}"
NODES="${2:-}"
CKPT="${3:-}"
PY="${4:-python3}"
if [ -z "$MODEL" ] || [ -z "$NODES" ] || [ -z "$CKPT" ]; then
    sed -n '2,20p' "$0"
    exit 2
fi

PROBE="$ROOT/bin/node_expert_probe"
if [ ! -x "$PROBE" ]; then
    echo "probe 不存在 —— 先建置：NODE_TOOLS=1 ./scripts/build-eval.sh"
    NODE_TOOLS=1 ./scripts/build-eval.sh || exit 1
fi

exec "$PY" Source/Engine/eval/check_node_expert_parity.py \
    --probe "$PROBE" --model "$MODEL" --nodes "$NODES" --ckpt "$CKPT"
