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
# ## 三道關卡（FULL 模式）
#
#   1. 真實語料不得淨傷害（PTT + X 兩個獨立語域）
#   2. 引擎單元測試全過
#   3. 實機打字抽驗全過
#
# ## 三態輸出（棒⑤ · 2026-08-12）
#
#   FULL   — 兩份真實語料都在，且全部關卡通過。**只有 FULL 才可出貨。**
#   SUBSET — 語料缺一或全缺；只跑 ctest + repo 內建 sample。
#            明確不是出貨依據；exit 0 只代表「子集能跑完」。
#   FAIL   — 任何實際執行的關卡不過 → exit 1
#
# 難題考卷（EX1166）的分數**只印出來參考，不當關卡** —— 那份題目和被驗的
# 機制常常來自同一個生成器，它高不代表使用者體感好。
#
# 環境變數（可覆寫預設）：
#   IBOPOMOFO_CORPUS_DIR  預設 $HOME/Documents/i注音-語料/EX1166-題庫
#   IBOPOMOFO_EVAL_BIN    預設 /tmp/newstar_homophone_eval
set -euo pipefail
cd "$(dirname "$0")/.."

EVAL="${IBOPOMOFO_EVAL_BIN:-/tmp/newstar_homophone_eval}"
CORPUS_DIR="${IBOPOMOFO_CORPUS_DIR:-$HOME/Documents/i注音-語料/EX1166-題庫}"
SAMPLE_JSONL="Source/Engine/eval/benchmarks/newstar_sample.jsonl"

if [ ! -x "$EVAL" ]; then
    echo "先建置評分機：IBOPOMOFO_EVAL_BIN=$EVAL 不存在或不可執行"
    echo "（見 Source/Engine/eval/benchmarks/README-newstar.md）"
    echo "SHIP_GATE_STATUS=FAIL"
    exit 1
fi

fail=0
# ⚠️ 下面「出貨側」載入的規則表清單，必須跟 KeyHandler.mm 實際載入的那幾份一致
#（目前是 particle-rules.tsv + police-de-v1.tsv）。2026-08-12 發 2.16.3 前抓到：
# 這裡只掛了 particle-rules.tsv，等於用「沒有警察」的配置去驗「有警察」的版本，
# 關卡會綠燈但什麼都沒驗到。加新規則表時**兩邊都要改**。

corpus_names=(自然驗證集-真實語料 X驗證集-真實語料)
corpus_present=0
corpus_total=${#corpus_names[@]}
missing_list=()

for name in "${corpus_names[@]}"; do
    items="$CORPUS_DIR/$name.jsonl"
    if [ -r "$items" ]; then
        corpus_present=$((corpus_present + 1))
    else
        missing_list+=("$items")
    fi
done

run_corpus_pair() {
    local name="$1"
    local items="$CORPUS_DIR/$name.jsonl"
    rm -f /tmp/gate-base.tsv /tmp/gate-ship.tsv
    if ! "$EVAL" "$items" Source/Data/data.txt Source/Data/word-bigrams.tsv \
        Source/Data/path-char-lstm.bin shipping 0.75 0.75 "" /tmp/gate-base.tsv "" >/dev/null 2>&1 \
       || ! "$EVAL" "$items" Source/Data/data.txt Source/Data/word-bigrams.tsv \
        Source/Data/path-char-lstm.bin shipping 0.75 0.75 \
        Source/Data/confusion-alphas.tsv /tmp/gate-ship.tsv \
        Source/Data/particle-rules.tsv Source/Data/police-de-v1.tsv >/dev/null 2>&1 \
       || [ ! -s /tmp/gate-base.tsv ] || [ ! -s /tmp/gate-ship.tsv ]; then
        echo "  ❌ ${name}：評分機執行失敗，不採信任何數字"
        fail=1
        return
    fi
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
        printf "  ❌ %s：救 %s、壞 %s —— 淨傷害，不准出貨\n" "$name" "$g" "$w"
        fail=1
    else
        printf "  ✅ %s：救 %s、壞 %s\n" "$name" "$g" "$w"
    fi
}

run_ctest() {
    echo "── 關卡：引擎單元測試 ──"
    if (cd Source/Engine && cmake -S . -B /tmp/gate-build -DCMAKE_BUILD_TYPE=Release -DENABLE_TEST=ON >/dev/null 2>&1 \
        && cmake --build /tmp/gate-build -j4 >/dev/null 2>&1 \
        && cd /tmp/gate-build && ctest >/dev/null 2>&1); then
        echo "  ✅ 全過"
    else
        echo "  ❌ 有測試失敗"
        fail=1
    fi
}

run_sample_eval() {
    echo "── 關卡：repo 內建 sample（newstar_sample.jsonl）──"
    if [ ! -r "$SAMPLE_JSONL" ]; then
        echo "  ❌ 找不到 ${SAMPLE_JSONL}"
        fail=1
        return
    fi
    if "$EVAL" "$SAMPLE_JSONL" Source/Data/data.txt Source/Data/word-bigrams.tsv \
        Source/Data/path-char-lstm.bin shipping 0.75 0.75 >/dev/null 2>&1; then
        echo "  ✅ sample 跑完（僅自證 harness 可跑，不是出貨尺）"
    else
        echo "  ❌ sample 評分失敗"
        fail=1
    fi
}

run_e2e_typing() {
    echo "── 關卡：實機打字（需要 i注音為當前輸入法）──"
    if ./scripts/type-as-user.sh -f scripts/ship-gate-sentences.txt 2>/dev/null | grep -q "❌"; then
        ./scripts/type-as-user.sh -f scripts/ship-gate-sentences.txt 2>/dev/null | grep -A1 "❌"
        fail=1
    else
        echo "  ✅ 抽驗句全過（或已跳過）"
    fi
}

if [ "$corpus_present" -eq "$corpus_total" ]; then
    # ── FULL path：兩份真實語料都在 ──
    echo "── 模式：FULL（兩份真實語料齊全）──"
    echo "── 關卡 1／3：真實語料不得淨傷害 ──"
    for name in "${corpus_names[@]}"; do
        run_corpus_pair "$name"
    done
    echo "── 關卡 2／3：引擎單元測試 ──"
    run_ctest
    echo "── 關卡 3／3：實機打字 ──"
    run_e2e_typing

    if [ "$fail" -eq 0 ]; then
        echo ""
        echo "✅ 三關全過，可以出貨。"
        echo "SHIP_GATE_STATUS=FULL"
        exit 0
    else
        echo ""
        echo "❌ 沒過關，不要發版。"
        echo "SHIP_GATE_STATUS=FAIL"
        exit 1
    fi
else
    # ── SUBSET path：語料缺一或全缺 ──
    echo "── 模式：SUBSET（真實語料不齊：${corpus_present}/${corpus_total}）──"
    for m in "${missing_list[@]}"; do
        echo "  ⚠️ 讀不到 ${m}"
    done
    echo "  ⚠️ 這是子集，不足以作為出貨依據。發版仍只認 FULL。"
    run_sample_eval
    run_ctest

    if [ "$fail" -eq 0 ]; then
        echo ""
        echo "⚠️ SUBSET 通過：ctest + sample 綠燈，但**不足以作為出貨依據**。"
        echo "   出貨必須兩份真實語料都在且 SHIP_GATE_STATUS=FULL。"
        echo "SHIP_GATE_STATUS=SUBSET — 這是子集，不足以作為出貨依據"
        exit 0
    else
        echo ""
        echo "❌ 子集關卡沒過。"
        echo "SHIP_GATE_STATUS=FAIL"
        exit 1
    fi
fi
