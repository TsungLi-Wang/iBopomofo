#!/bin/bash
# correction-census.sh — 手動校正 log 的彙總普查（只印統計，不印任何原文）
#
# ## 為什麼要有這支
#
# `docs/decisions/0003` 押的注是「真人的手動校正是下一段燃料」。那條路要成立，
# 第一個要回答的問題不是演算法，是**到底收到多少、長什麼樣**。
# 這支就是回答那一題，而且做成可重跑的，免得每次都有人手動 awk 一輪。
#
# ## 隱私（硬性）
#
# `manual-correction.log` 是使用者打過的字。**這支腳本永遠不印句子、不印
# left_context、不印時間戳**，只印次數與 wrong→chosen 的字對。
# 預設不寫檔（只到 stdout）。輸出可以貼進 CHANGELOG／issue，原文不行。
#
# schema v1（`Source/ManualCorrectionLog.swift`）：
#   schemaVer \t ISO8601 \t reading \t left_context \t wrong_char \t chosen
# 舊格式（v1 之前）欄位較少，這支會分開數，不混在一起算。
#
# 用法：
#   ./scripts/correction-census.sh            # 兩個資料目錄都看
#   ./scripts/correction-census.sh --top 20   # 配對排行列幾名（預設 10）
#
# 離開碼：0＝至少讀到一個 log；1＝一個都讀不到（TCC 或還沒有校正紀錄）。
# **讀不到不算整棒失敗** —— 它只表示這台機器上還沒有資料。
set -uo pipefail

TOP=10
while [ $# -gt 0 ]; do
    case "$1" in
        --top) TOP="$2"; shift 2 ;;
        -h|--help) sed -n '2,25p' "$0"; exit 0 ;;
        *) echo "未知參數：$1" >&2; exit 2 ;;
    esac
done

found=0

census_one() {
    local label="$1" path="$2"
    echo "── $label ──"
    if [ ! -e "$path" ]; then
        echo "  （沒有這個檔 —— 這台機器還沒有校正紀錄，或用的是另一個資料目錄）"
        echo
        return
    fi
    if [ ! -r "$path" ]; then
        echo "  ⚠️ 檔在但讀不到（多半是 macOS TCC 擋的，POSIX 權限看起來正常也會這樣）。"
        echo "     不是失敗，只是這個執行環境拿不到；換終端機或給權限再跑。"
        echo
        return
    fi
    found=1

    awk -F'\t' -v top="$TOP" '
    {
        total++
        if ($1 == "2" && NF == 10) {
            # schema v2（棒⑲）：engine_choice 在第 5 欄、user_choice 在第 6 欄，
            # 版面是 v1 的嚴格超集，所以配對統計與 v1 完全共用。
            # 以前這裡沒有 v2 分派，v2 的行會被算進「v1 之前的舊格式」。
            v2++
            reading = $3; wrong = $5; chosen = $6
            etype[$7]++
            if (chosen != "") has_chosen++
            if (wrong == "") empty_wrong++
            if (wrong != "" && chosen != "") {
                npair++
                if (wrong == chosen) same++
                else { pair[wrong "→" chosen]++; nreal++ }
            }
            if (reading != "") readings[reading]++
        } else if ($1 == "1" && NF == 6) {
            v1++
            reading = $3; wrong = $5; chosen = $6
            if (chosen != "") has_chosen++
            if (wrong == "") empty_wrong++
            if (wrong != "" && chosen != "") {
                npair++
                if (wrong == chosen) {
                    # wrong == chosen ＝ 使用者開了候選窗又選回同一個字，
                    # 不是校正事件。混進來會高估「真人批改」的量。
                    same++
                } else {
                    pair[wrong "→" chosen]++
                    nreal++
                }
            }
            if (reading != "") readings[reading]++
        } else {
            legacy++
        }
    }
    END {
        printf "  總行數 %d（schema v2 %d、v1 %d、v1 之前的舊格式 %d）\n", total, v2 + 0, v1, legacy
        if (v2 + 0 > 0) {
            printf "  v2 event_type："
            for (e in etype) printf " %s=%d", e, etype[e]
            printf "\n"
        }
        if (v1 + v2 == 0) { print "  沒有 v1/v2 行，以下不統計。"; print ""; exit }
        printf "  有 chosen %d 筆；wrong_char 空白 %d 筆\n", has_chosen, empty_wrong
        printf "  可成對（wrong→chosen 兩欄都有）%d 筆\n", npair
        printf "  其中 wrong == chosen（選回同一個字，**不是校正**）%d 筆\n", same + 0
        printf "  ▶ 真正換了字的校正事件：%d 筆，相異配對 %d 種\n", nreal + 0, length(pair)
        n = 0
        for (k in pair) { arr[++n] = pair[k] "\t" k }
        # 由大到小（資料量小，簡單插入排序就夠）
        for (i = 2; i <= n; i++) {
            t = arr[i]; split(t, tf, "\t")
            j = i - 1
            while (j >= 1) { split(arr[j], jf, "\t"); if (jf[1] + 0 >= tf[1] + 0) break; arr[j+1] = arr[j]; j-- }
            arr[j+1] = t
        }
        if (n > 0) {
            printf "  真正換了字的配對前 %d 名：\n", (n < top ? n : top)
            for (i = 1; i <= n && i <= top; i++) {
                split(arr[i], f, "\t")
                printf "    %-12s %s 次\n", f[2], f[1]
            }
        }
        printf "  出現過的讀音 %d 種\n", length(readings)
        print ""
    }' "$path"
}

echo "手動校正 log 普查（只有次數與字對，沒有任何原文）"
echo
census_one "iBopomofo（現役）" "$HOME/Library/Application Support/iBopomofo/manual-correction.log"
census_one "McBopomofo（棒⑥ 改名前的舊資料目錄）" "$HOME/Library/Application Support/McBopomofo/manual-correction.log"

# ── 分母（棒㉓ decision census）──
# 沒有這一段，上面的配對數只是分子；錯誤率在結構上算不出來。
census_denominator() {
    local path="$HOME/Library/Application Support/iBopomofo/decision-census.log"
    echo "── 決策分母（decision-census.log）──"
    if [ ! -e "$path" ]; then
        echo "  （還沒有這個檔 —— 帶 decision census 的 build 尚未安裝，或還沒定案過）"
        echo "  ⚠️ 沒有分母就只有分子：錯誤率不可計算。"
        echo
        return
    fi
    awk -F'\t' '
    $1 == "1" && NF == 5 { commits++; nodes += $3; chars += $4; ov += $5 }
    END {
        if (commits == 0) { print "  檔在但沒有可解析的行。"; print ""; exit }
        printf "  定案次數 %d，引擎決策（節點）%d，字數 %d\n", commits, nodes, chars
        printf "  其中被使用者覆寫的節點 %d\n", ov
        printf "  ▶ 節點層修正率 %.3f%%（%d / %d）\n", (nodes ? 100 * ov / nodes : 0), ov, nodes
        print "  註：這是「使用者出手改過」的比率，不是引擎正確率 —— 沒察覺的錯不在分子裡。"
        print ""
    }' "$path"
}

census_denominator

if [ "$found" -eq 0 ]; then
    echo "兩個位置都沒讀到 log。"
    exit 1
fi
exit 0
