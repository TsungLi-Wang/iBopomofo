#!/bin/bash
# model-ab.sh — 換神經權重時的判準：兩個模型逐題配對比較。
#
# ## 為什麼要有這支（別再用 ship-gate 判這件事）
#
# `ship-gate.sh` 比的是「規則開 vs 規則關」，**兩邊用同一個 path-char-lstm.bin**。
# 換權重它抓不到 —— 2026-08-13（棒⑩）那個在真實語料上淨傷害 −36（p=4.4e-05）
# 的作做坐座模型，照樣跑出 `SHIP_GATE_STATUS=CORE`，數字還跟前一版一模一樣。
#
# 所以：**改規則／詞庫 → ship-gate CORE；換 path-char-lstm.bin → CORE 是必要條件，
# 但判準是這支。** CI 綠燈兩者都不是。
#
# 統計交給 benchmarks/compare_dumps.py（McNemar + 逐 pair + train/heldout 分開），
# 這支只負責「用出貨配置各跑一次、把 dump 餵進去」。不要在這裡重寫檢定。
#
# ## 用法
#
#   ./scripts/model-ab.sh <before.bin> <after.bin>          # 預設只跑 sample（煙霧）
#   ./scripts/model-ab.sh --self                            # 兩邊都用出貨權重 → 必須 0/0
#   ./scripts/model-ab.sh --self --items <a.jsonl> --items <b.jsonl>
#   ./scripts/model-ab.sh old.bin new.bin \
#       --items "$HOME/Documents/i注音-語料/EX1166-題庫/自然驗證集-真實語料.jsonl" \
#       --items "$HOME/Documents/i注音-語料/EX1166-題庫/X驗證集-真實語料.jsonl"
#
# `--self` 是**回歸測試**：同一個權重跑兩次，救／壞必須都是 0。不是 0 就表示
# 評分機或這支腳本本身不確定性，之後量到的任何差異都不可信 —— 先修這個。
set -uo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"

EVAL="${IBOPOMOFO_EVAL_BIN:-bin/newstar_homophone_eval}"
SHIPPING_BIN="Source/Data/path-char-lstm.bin"
COMPARE="Source/Engine/eval/benchmarks/compare_dumps.py"
SAMPLE="Source/Engine/eval/benchmarks/newstar_sample.jsonl"

self_mode=0
before=""
after=""
items=()

while [ $# -gt 0 ]; do
    case "$1" in
        --self)  self_mode=1; shift ;;
        --items) items+=("$2"); shift 2 ;;
        -h|--help) sed -n '2,32p' "$0"; exit 0 ;;
        -*) echo "未知參數：$1" >&2; exit 2 ;;
        *)
            if [ -z "$before" ]; then before="$1"
            elif [ -z "$after" ]; then after="$1"
            else echo "多餘的參數：$1" >&2; exit 2
            fi
            shift ;;
    esac
done

if [ "$self_mode" -eq 1 ]; then
    if [ -n "$before" ] || [ -n "$after" ]; then
        echo "--self 不接模型路徑（兩邊都用出貨權重 $SHIPPING_BIN）" >&2
        exit 2
    fi
    before="$SHIPPING_BIN"
    after="$SHIPPING_BIN"
fi

if [ -z "$before" ] || [ -z "$after" ]; then
    echo "用法：$0 <before.bin> <after.bin> [--items x.jsonl]…   或   $0 --self [--items …]" >&2
    exit 2
fi
for m in "$before" "$after"; do
    [ -r "$m" ] || { echo "讀不到模型：$m" >&2; exit 2; }
done

# 預設只跑 sample —— 真實語料要明確指定，免得手一滑就是幾十分鐘。
if [ ${#items[@]} -eq 0 ]; then
    items=("$SAMPLE")
fi

if [ ! -x "$EVAL" ]; then
    echo "評分機不存在（$EVAL）—— 先建置："
    ./scripts/build-eval.sh || exit 1
fi

# ── 出貨配置：必須與 ship-gate.sh 的「shipping」那一路完全相同 ──
# argv: <items> <data.txt> <word-bigrams.tsv> <model> shipping <λ> <ν> <alphas> <dump> <規則表…>
# 加新規則表時，**ship-gate.sh 與這裡兩邊都要改**，否則會拿「沒有警察」的配置
# 去驗「有警察」的版本，兩支腳本各驗一個不同的東西（2026-08-12 踩過同一個坑）。
run_eval() {   # $1=模型 $2=題庫 $3=dump 路徑
    "$EVAL" "$2" \
        Source/Data/data.txt Source/Data/word-bigrams.tsv \
        "$1" shipping 0.75 0.75 \
        Source/Data/confusion-alphas.tsv "$3" \
        Source/Data/particle-rules.tsv Source/Data/police-de-v1.tsv \
        >/dev/null 2>&1
}

echo "before : $before"
echo "after  : $after"
[ "$self_mode" -eq 1 ] && echo "模式   : --self（同一個權重跑兩次；救／壞必須都是 0）"
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
    if ! run_eval "$before" "$item" "$tmpdir/before.tsv" \
       || ! run_eval "$after" "$item" "$tmpdir/after.tsv" \
       || [ ! -s "$tmpdir/before.tsv" ] || [ ! -s "$tmpdir/after.tsv" ]; then
        echo "  ❌ 評分機執行失敗 —— 不採信任何數字"
        summary+=("$name	FAIL	評分機執行失敗")
        rc=1
        continue
    fi

    # 統計一律走 compare_dumps.py（McNemar／逐 pair／train-heldout 都在那裡）
    python3 "$COMPARE" "$tmpdir/before.tsv" "$tmpdir/after.tsv" --items "$item" --show 0

    # 總表用的救／壞：從同兩份 dump 再數一次總計（不重寫檢定，只數 b/c）
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
        echo "  ❌ --self 但救=$gain 壞=$loss（應為 0／0）—— 評分流程不是決定性的，"
        echo "     之後量到的任何差異都不可信。先修這個再談換模型。"
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
echo "※ p 值與逐 pair 拆解見上面每份題庫的 compare_dumps 輸出（heldout 那欄才算數）。"
if [ "$self_mode" -eq 1 ]; then
    if [ "$rc" -eq 0 ]; then
        echo "✅ --self 全部 0／0：評分流程是決定性的。"
    else
        echo "❌ --self 沒有全部 0／0。"
    fi
fi
exit "$rc"
