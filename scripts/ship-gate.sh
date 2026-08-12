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
# ## 兩種完全不同的關卡（2026-08-12 晚強制拆開 —— 勿再混為一談）
#
#   ┌─────────────────────────────────────────────────────────────┐
#   │  CORE（關卡 1＋2）＝ 離線、不開視窗、不碰輸入法選單          │
#   │    1. 真實語料不得淨傷害（PTT + X）                           │
#   │    2. 引擎單元測試                                          │
#   │  → 這才是「選字有沒有變爛」的出貨尺。AI／背景 session 只跑這個。│
#   └─────────────────────────────────────────────────────────────┘
#   ┌─────────────────────────────────────────────────────────────┐
#   │  E2E（關卡 3）＝ 開 TextEdit、送鍵、要輔助使用權限＋i注音     │
#   │  → 驗的是「裝好的 app 在 GUI 裡能不能打」，不是選字演算法。   │
#   │  → 預設不跑。要跑：SHIP_GATE_E2E=1（人在螢幕前、自願）。    │
#   │  → 跑不動＝SKIP，絕不是「再試一次選輸入法」。                │
#   └─────────────────────────────────────────────────────────────┘
#
# ## 狀態輸出
#
#   CORE   — 語料齊、關卡 1＋2 全過；E2E 跳過或未要求。**預設出貨依據。**
#   FULL   — CORE ＋ 關卡 3 也過（只有 SHIP_GATE_E2E=1 且環境健康時才可能）。
#   SUBSET — 語料不齊；只跑 ctest + sample。不是出貨依據。
#   FAIL   — CORE 關卡失敗；或你強制 E2E=1 但 E2E 真的沒過。
#
# 難題考卷（EX1166）的分數**只印出來參考，不當關卡**。
#
# 環境變數：
#   IBOPOMOFO_CORPUS_DIR  預設 $HOME/Documents/i注音-語料/EX1166-題庫
#   IBOPOMOFO_EVAL_BIN    預設 bin/newstar_homophone_eval
#   SHIP_GATE_E2E         預設 0（不跑實機打字）。設 1 才跑關卡 3。
set -euo pipefail
cd "$(dirname "$0")/.."

EVAL="${IBOPOMOFO_EVAL_BIN:-bin/newstar_homophone_eval}"
CORPUS_DIR="${IBOPOMOFO_CORPUS_DIR:-$HOME/Documents/i注音-語料/EX1166-題庫}"
SAMPLE_JSONL="Source/Engine/eval/benchmarks/newstar_sample.jsonl"
# 預設 0：AI／背景／擦屁股 session 不准為了「選不到輸入法」耗掉整晚。
SHIP_GATE_E2E="${SHIP_GATE_E2E:-0}"

if [ ! -x "$EVAL" ]; then
    echo "先建置評分機：IBOPOMOFO_EVAL_BIN=$EVAL 不存在或不可執行"
    echo "  → 跑 ./scripts/build-eval.sh 即可（約 20 秒）"
    echo "（細節見 Source/Engine/eval/benchmarks/README-newstar.md）"
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
    # 2026-08-12：原本三步（configure / build / ctest）串成一個 if，任一步失敗都印
    # 「有測試失敗」。實際踩到：PATH 裡沒有 cmake（Homebrew 不在 PATH）→ 印出
    # 「有測試失敗」，看起來像引擎壞了，其實一個測試都沒跑到。分開報。
    if ! command -v cmake >/dev/null 2>&1; then
        echo "  ❌ 找不到 cmake —— 這一關沒有真的跑到測試"
        echo "     （PATH=$PATH）"
        fail=1
        return
    fi
    local gate_build="${GATE_BUILD_DIR:-$PWD/build/gate-build}"
    if ! (cd Source/Engine && cmake -S . -B "$gate_build" -DCMAKE_BUILD_TYPE=Release -DENABLE_TEST=ON >/dev/null 2>&1 \
          && cmake --build "$gate_build" -j4 >/dev/null 2>&1); then
        echo "  ❌ 引擎測試「建置」失敗 —— 這一關沒有真的跑到測試"
        echo "     重跑看錯誤：cd Source/Engine && cmake -S . -B \"$gate_build\" -DENABLE_TEST=ON && cmake --build \"$gate_build\""
        fail=1
        return
    fi
    if (cd "$gate_build" && ctest >/dev/null 2>&1); then
        echo "  ✅ 全過"
    else
        echo "  ❌ 有測試失敗（建置是成功的，是測試本身沒過）"
        echo "     看細節：cd \"$gate_build\" && ctest --output-on-failure"
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

# E2E 結果：skip | pass | fail（只在 SHIP_GATE_E2E=1 時才會是 pass/fail）
e2e_result="skip"

run_e2e_typing() {
    # 回傳：設 e2e_result；只有明確引擎／基準迴歸才設 fail=1。
    # harness 環境問題 → e2e_result=skip 或 fail（僅當強制要求時），並印清楚原因。
    echo "── 關卡 3：實機打字（可選 · GUI／輸入法／輔助使用）──"
    echo "  這關與關卡 1＋2 無關：不驗證選字演算法，只驗證「裝好的 app 在 TextEdit 裡能出字」。"
    echo "  需求：螢幕前有人、輔助使用權限、i注音已加入清單。選不到輸入法＝環境問題，不是產品壞了。"

    if [ "$SHIP_GATE_E2E" != "1" ]; then
        echo "  ⏭  跳過（SHIP_GATE_E2E=${SHIP_GATE_E2E}；預設不跑）。"
        echo "     要跑：SHIP_GATE_E2E=1 ./scripts/ship-gate.sh"
        echo "     ⚠️ AI／背景 session：禁止為了這一關去「修好輸入法切換」而重試多輪。"
        e2e_result="skip"
        return
    fi

    # ── 判定基準（2026-08-12 定案）──
    # 量「對基準的淨傷害」，不是「是否等於理想答案」。
    # 有基準 → 輸出 ≠ 基準才算迴歸；無基準 → 首次建檔、本關不擋。
    local baseline="scripts/ship-gate-baseline.tsv"
    local cur out rc
    cur="$(mktemp)"
    set +e
    out="$(./scripts/type-as-user.sh -f scripts/ship-gate-sentences.txt 3>"$cur" 2>&1)"
    rc=$?
    set -e
    printf '%s\n' "$out" | sed 's/^/  /'

    # harness 沒跑起來／中途當英文鍵 → 環境失敗，不是 CORE 失敗
    if [ ! -s "$cur" ]; then
        echo "  ⚠️  E2E 環境沒就緒（一句都沒打到）。CORE 仍以關卡 1＋2 為準；不重試。"
        e2e_result="fail"
        rm -f "$cur"
        # 只有強制 E2E=1 才把整體打成 fail
        fail=1
        return
    fi
    if printf '%s\n' "$out" | grep -qE 'harness-latin-keys|input source lost mid-run|TYPE_AS_USER=FAIL\(harness'; then
        echo "  ⚠️  E2E harness 環境失敗（輸入法／送鍵），不是選字迴歸。不重試、不蠻幹。"
        e2e_result="fail"
        fail=1
        rm -f "$cur"
        return
    fi

    if [ ! -f "$baseline" ]; then
        cp "$cur" "$baseline"
        echo "  ⚠️  首次建立基準：$baseline（本關不擋）"
        e2e_result="pass"
        rm -f "$cur"
        return
    fi

    local diffout
    diffout="$(diff "$baseline" "$cur" || true)"
    if [ -z "$diffout" ]; then
        echo "  ✅ 與基準逐句相同 —— 零淨傷害"
        local known
        known="$(awk -F'\t' '$2 != $3 {print "     · " $2 " → " $3}' "$cur" || true)"
        if [ -n "$known" ]; then
            echo "  ℹ️  既有選字缺陷（只報不擋；見 issue #10）："
            printf '%s\n' "$known"
        fi
        e2e_result="pass"
    else
        echo "  ❌ 與基準不同 —— 有迴歸："
        printf '%s\n' "$diffout" | sed 's/^/     /'
        e2e_result="fail"
        fail=1
    fi
    rm -f "$cur"
}

if [ "$corpus_present" -eq "$corpus_total" ]; then
    # ── CORE path：兩份真實語料都在（離線關卡）──
    echo "── 模式：CORE（兩份真實語料齊全 · 離線關卡 1＋2）──"
    echo "── 關卡 1／2：真實語料不得淨傷害 ──"
    for name in "${corpus_names[@]}"; do
        run_corpus_pair "$name"
    done
    echo "── 關卡 2／2：引擎單元測試 ──"
    run_ctest

    core_fail=$fail
    # 關卡 3 預設跳過；只有 SHIP_GATE_E2E=1 才跑
    run_e2e_typing

    if [ "$core_fail" -ne 0 ]; then
        echo ""
        echo "❌ CORE 沒過（語料淨傷害或單元測試）—— 不准出貨。"
        echo "SHIP_GATE_STATUS=FAIL"
        exit 1
    fi

    if [ "$e2e_result" = "pass" ]; then
        echo ""
        echo "✅ CORE 全過，且 E2E 也過 → FULL。"
        echo "SHIP_GATE_STATUS=FULL"
        exit 0
    fi
    if [ "$e2e_result" = "fail" ] && [ "$SHIP_GATE_E2E" = "1" ]; then
        echo ""
        echo "❌ 你要求了 E2E（SHIP_GATE_E2E=1）但沒過。"
        echo "   CORE（選字）是綠的；失敗在 GUI／輸入法／基準。不要用「再選一次輸入法」當唯一解法。"
        echo "SHIP_GATE_STATUS=FAIL"
        exit 1
    fi

    echo ""
    echo "✅ CORE 全過（關卡 1＋2）—— 可作出貨依據。"
    if [ "$e2e_result" = "skip" ]; then
        echo "   E2E 已跳過（預設）。需要時：SHIP_GATE_E2E=1 ./scripts/ship-gate.sh"
    fi
    echo "SHIP_GATE_STATUS=CORE"
    exit 0
else
    # ── SUBSET path：語料缺一或全缺 ──
    echo "── 模式：SUBSET（真實語料不齊：${corpus_present}/${corpus_total}）──"
    for m in "${missing_list[@]}"; do
        echo "  ⚠️ 讀不到 ${m}"
    done
    echo "  ⚠️ 這是子集，不足以作為出貨依據。發版認 CORE／FULL（語料要齊）。"
    run_sample_eval
    run_ctest

    if [ "$fail" -eq 0 ]; then
        echo ""
        echo "⚠️ SUBSET 通過：ctest + sample 綠燈，但**不足以作為出貨依據**。"
        echo "   出貨必須兩份真實語料都在且 SHIP_GATE_STATUS=CORE 或 FULL。"
        echo "SHIP_GATE_STATUS=SUBSET — 這是子集，不足以作為出貨依據"
        exit 0
    else
        echo ""
        echo "❌ 子集關卡沒過。"
        echo "SHIP_GATE_STATUS=FAIL"
        exit 1
    fi
fi
