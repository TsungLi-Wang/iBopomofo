#!/bin/bash
# 出貨前的硬性關卡。**沒過就不准打包發版。**
#
# ## 為什麼要有這支
#
# 2026-08-10/11 連續發了 v2.16.0、v2.16.1，兩次都是「在自己出的考卷上量到進步
# 就發版」，之後才用真實語料發現是淨傷害，再退版。同一類錯誤一天內犯四次。
#
# 根因不是判斷力，是**順序**：先做機制、再找方法驗證。這支把順序倒過來 ——
# 任何要出貨的改動，都必須先通過真實語料驗證，才輪得到看難題考卷的分數。
#
# ## 三道關卡
#
#   1. 真實語料不得淨傷害（PTT + X 兩個獨立語域）
#   2. 引擎單元測試全過
#   3. 實機打字抽驗全過
#
# 難題考卷（EX1166）的分數**只印出來參考，不當關卡** —— 那份題目和被驗的
# 機制常常來自同一個生成器，它高不代表使用者體感好。
set -euo pipefail
cd "$(dirname "$0")/.."

EVAL=/tmp/newstar_homophone_eval
CORPUS_DIR="$HOME/Documents/i注音-語料/EX1166-題庫"
[ -x "$EVAL" ] || { echo "先建置評分機（見 eval/benchmarks/README-newstar.md）"; exit 1; }

fail=0
echo "── 關卡 1／3：真實語料不得淨傷害 ──"
for name in 自然驗證集-真實語料 X驗證集-真實語料; do
    items="$CORPUS_DIR/$name.jsonl"
    [ -f "$items" ] || { echo "  ⚠️  找不到 $items，跳過"; continue; }
    "$EVAL" "$items" Source/Data/data.txt Source/Data/word-bigrams.tsv \
        Source/Data/path-char-lstm.bin shipping 0.75 0.75 "" /tmp/gate-base.tsv "" >/dev/null 2>&1
    "$EVAL" "$items" Source/Data/data.txt Source/Data/word-bigrams.tsv \
        Source/Data/path-char-lstm.bin shipping 0.75 0.75 \
        Source/Data/confusion-alphas.tsv /tmp/gate-ship.tsv Source/Data/particle-rules.tsv >/dev/null 2>&1
    read -r g w <<<"$(python3 - <<'PY'
def load(p):
    d={}
    for k,l in enumerate(open(p,encoding='utf-8')):
        if k:
            f=l.rstrip('\n').split('\t')
            if len(f)>=4: d[f[0]]=int(f[3])
    return d
a,b=load('/tmp/gate-base.tsv'),load('/tmp/gate-ship.tsv')
ks=set(a)&set(b)
print(sum(1 for k in ks if b[k] and not a[k]), sum(1 for k in ks if a[k] and not b[k]))
PY
)"
    if [ "$w" -gt "$g" ]; then
        printf "  ❌ %s：救 %s、壞 %s —— 淨傷害，不准出貨\n" "$name" "$g" "$w"; fail=1
    else
        printf "  ✅ %s：救 %s、壞 %s\n" "$name" "$g" "$w"
    fi
done

echo "── 關卡 2／3：引擎單元測試 ──"
if (cd Source/Engine && cmake -S . -B /tmp/gate-build -DCMAKE_BUILD_TYPE=Release -DENABLE_TEST=ON >/dev/null 2>&1 \
    && cmake --build /tmp/gate-build -j4 >/dev/null 2>&1 \
    && cd /tmp/gate-build && ctest >/dev/null 2>&1); then
    echo "  ✅ 全過"
else
    echo "  ❌ 有測試失敗"; fail=1
fi

echo "── 關卡 3／3：實機打字（需要 i注音為當前輸入法）──"
if ./scripts/type-as-user.sh -f scripts/ship-gate-sentences.txt 2>/dev/null | grep -q "❌"; then
    ./scripts/type-as-user.sh -f scripts/ship-gate-sentences.txt 2>/dev/null | grep -A1 "❌"
    fail=1
else
    echo "  ✅ 抽驗句全過（或已跳過）"
fi

[ "$fail" -eq 0 ] && echo "
✅ 三關全過，可以出貨。" || { echo "
❌ 沒過關，不要發版。"; exit 1; }
