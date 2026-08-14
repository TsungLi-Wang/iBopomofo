#!/bin/bash
# node-expert-ab.sh — 節點層專家的判準：**同一份出貨配置，只差專家開不開**。
#
# ## 三把尺別拿錯（棒⑩ 踩過）
#
#   ship-gate.sh   比「規則開 vs 規則關」，兩邊同一顆 path-char-lstm.bin
#                  → 出貨的必要條件，抓不到專家
#   model-ab.sh    比「兩顆 path-char-lstm.bin」
#                  → 換**路徑層**權重用。這顆專家不是那個檔，拿它會假綠燈
#   本支           比「專家關 vs 專家開」
#                  → 換**節點層**專家用
#
# 統計一律交給 compare_dumps.py（McNemar），不在這裡重寫檢定。
# 誤傷另外交給 node_expert_collateral.py —— 上面那些尺只看目標那一個字。
#
# ## 用法
#
#   ./scripts/node-expert-ab.sh <model.bin> --tau 3.0 \
#       --items "$HOME/Documents/i注音-語料/EX1166-題庫/自然驗證集-真實語料.jsonl" \
#       --items "$HOME/Documents/i注音-語料/EX1166-題庫/X驗證集-真實語料.jsonl"
#   ./scripts/node-expert-ab.sh --self          # 兩邊都不掛 → 必須 0/0
#
# ⚠️ `--tau` 只准在抽取資料的 held-out 上定好再帶進來。在這裡掃 τ 挑最高的
# 報出去，就是 docs/dead-ends.md B 節那條「同一份資料選參數又報成績」。
set -uo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"

EVAL="${IBOPOMOFO_EVAL_BIN:-bin/newstar_homophone_eval}"
COMPARE="Source/Engine/eval/benchmarks/compare_dumps.py"
COLLATERAL="Source/Engine/eval/benchmarks/node_expert_collateral.py"
SAMPLE="Source/Engine/eval/benchmarks/newstar_sample.jsonl"

self_mode=0
model=""
tau=""
readings=""
group="作做坐座"
items=()

while [ $# -gt 0 ]; do
    case "$1" in
        --self)     self_mode=1; shift ;;
        --items)    items+=("$2"); shift 2 ;;
        --tau)      tau="$2"; shift 2 ;;
        --readings) readings="$2"; shift 2 ;;
        --group)    group="$2"; shift 2 ;;
        -h|--help)  sed -n '2,30p' "$0"; exit 0 ;;
        -*) echo "未知參數：$1" >&2; exit 2 ;;
        *)
            if [ -z "$model" ]; then model="$1"
            else echo "多餘的參數：$1" >&2; exit 2
            fi
            shift ;;
    esac
done

if [ "$self_mode" -eq 0 ] && [ -z "$model" ]; then
    echo "用法：$0 <model.bin> [--tau T] [--readings ㄗㄨㄛˋ] [--items x.jsonl]… 或 $0 --self" >&2
    exit 2
fi
if [ "$self_mode" -eq 1 ] && [ -n "$model" ]; then
    echo "--self 不接模型路徑（兩邊都不掛）" >&2
    exit 2
fi
if [ -n "$model" ] && [ ! -r "$model" ]; then
    echo "讀不到模型：$model" >&2
    exit 2
fi
if [ ${#items[@]} -eq 0 ]; then items=("$SAMPLE"); fi
if [ ! -x "$EVAL" ]; then
    echo "評分機不存在（$EVAL）—— 先建置："
    ./scripts/build-eval.sh || exit 1
fi

# ── 出貨配置：必須與 ship-gate.sh／model-ab.sh 的 shipping 那一路完全相同 ──
run_eval() {   # $1=專家模型（空＝不掛） $2=題庫 $3=dump $4=額外 log
    IBOPOMOFO_NODE_EXPERT="$1" \
    IBOPOMOFO_NODE_EXPERT_TAU="${tau:-0}" \
    IBOPOMOFO_NODE_EXPERT_READINGS="$readings" \
    "$EVAL" "$2" \
        Source/Data/data.txt Source/Data/word-bigrams.tsv \
        Source/Data/path-char-lstm.bin shipping 0.75 0.75 \
        Source/Data/confusion-alphas.tsv "$3" \
        Source/Data/particle-rules.tsv Source/Data/police-de-v1.tsv \
        >"${4:-/dev/null}" 2>&1
}

after_model="$model"
[ "$self_mode" -eq 1 ] && after_model=""

echo "before : （專家關）"
echo "after  : ${after_model:-（專家關）}"
[ -n "$tau" ] && echo "tau    : $tau"
echo "開火組 : ${readings:-（預設：ㄗㄨㄛˋ）}"
echo "評分機 : $EVAL"
echo

tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT
rc=0
summary=()

for item in "${items[@]}"; do
    name="$(basename "$item" .jsonl)"
    if [ ! -r "$item" ]; then
        echo "── $name ── ⚠️ 讀不到題庫：$item（跳過，不造數字）"
        summary+=("$name	SKIP	讀不到題庫")
        rc=1
        continue
    fi

    echo "── $name ──"
    if ! run_eval "" "$item" "$tmpdir/before.tsv" \
       || ! run_eval "$after_model" "$item" "$tmpdir/after.tsv" "$tmpdir/after.log" \
       || [ ! -s "$tmpdir/before.tsv" ] || [ ! -s "$tmpdir/after.tsv" ]; then
        echo "  ❌ 評分機執行失敗 —— 不採信任何數字"
        summary+=("$name	FAIL	評分機執行失敗")
        rc=1
        continue
    fi

    grep -h "^NODE_EXPERT" "$tmpdir/after.log" 2>/dev/null || true
    python3 "$COMPARE" "$tmpdir/before.tsv" "$tmpdir/after.tsv" --items "$item" --show 0
    python3 "$COLLATERAL" "$tmpdir/before.tsv" "$tmpdir/after.tsv" \
        --items "$item" --group "$group"

    read -r gain loss n <<<"$(python3 - "$tmpdir/before.tsv" "$tmpdir/after.tsv" <<'PY'
import sys
def load(p):
    d = {}
    with open(p, encoding='utf-8') as fh:
        next(fh)
        for line in fh:
            f = line.rstrip('\n').split('\t')
            if len(f) >= 4:
                d[f[0]] = int(f[3])
    return d
a, b = load(sys.argv[1]), load(sys.argv[2])
ks = a.keys() & b.keys()
print(sum(1 for k in ks if b[k] and not a[k]),
      sum(1 for k in ks if a[k] and not b[k]),
      len(ks))
PY
)"
    summary+=("$name	$gain	$loss	$n")
    if [ "$self_mode" -eq 1 ] && { [ "$gain" -ne 0 ] || [ "$loss" -ne 0 ]; }; then
        echo "  ❌ --self 但救=$gain 壞=$loss（應為 0／0）—— 評分流程不是決定性的。"
        rc=1
    fi
    echo
done

echo "════ 總表 ════"
printf '%-28s %6s %6s %6s %7s\n' 題庫 救 壞 淨 題數
for row in "${summary[@]}"; do
    IFS=$'\t' read -r name a b c <<<"$row"
    if [ "$a" = "SKIP" ] || [ "$a" = "FAIL" ]; then
        printf '%-28s %s（%s）\n' "$name" "$a" "$b"
        continue
    fi
    printf '%-28s %6s %6s %+6d %7s' "$name" "$a" "$b" "$((a - b))" "$c"
    if [ "$c" -lt 100 ]; then
        printf '   ← 分母 <100：只算煙霧／樣本，不下「有效／無效」\n'
    else
        printf '\n'
    fi
done
echo
echo "※ p 值與逐組拆解見上面每份題庫的 compare_dumps 輸出（heldout 那欄才算數）。"
exit "$rc"
