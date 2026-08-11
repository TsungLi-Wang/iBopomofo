#!/bin/bash
# 檢查一批背景工作是不是「正常完成」，不是只看檔案有沒有出現。
#
# ## 為什麼要有這支
#
# 2026-08-11 兩次被騙：
#   1. 評分機逾時被砍，留下 3,701 行的殘檔（應有 5,906），我直接拿去算，
#      到報 UnicodeDecodeError 才發現
#   2. grok 迴圈重複同一句 880 次，我看到「29,372 行」還以為豐收
#
# 兩次都不是主動發現的。所以把「怎樣算正常完成」寫成可執行的檢查。
#
# ⚠️ 變數後面緊接全形字元一律用 ${VAR} —— 不然 shell 會把全形標點
#    算進變數名。同一個坑今天踩第二次（第一次是 package-dmg.sh 的 $OUT（）。
#
# 用法：
#   ./scripts/check-batch.sh grok  <目錄> <預期批數>
#   ./scripts/check-batch.sh dump  <檔案> <預期行數>
set -euo pipefail
kind="${1:?grok|dump}"

case "$kind" in
grok)
    dir="${2:?目錄}"; want="${3:?預期批數}"
    files=$(ls "$dir"/*.md 2>/dev/null | wc -l | tr -d ' ')
    done_n=0; empty=0; loop=0
    for f in "$dir"/*.md; do
        [ -f "$f" ] || continue
        grep -q "^合計" "$f" 2>/dev/null && done_n=$((done_n+1))
        [ -s "$f" ] || empty=$((empty+1))
        # 迴圈偵測：同一行重複超過 20 次
        if [ "$(sort "$f" | uniq -c | sort -rn | head -1 | awk '{print $1}')" -gt 20 ] 2>/dev/null; then
            loop=$((loop+1)); echo "  ⚠️  $(basename "$f") 疑似迴圈重複"
        fi
    done
    running=$(pgrep -f 'grok -p' | wc -l | tr -d ' ')
    echo "檔案 $files/${want}、完成 ${done_n}、空檔 ${empty}、疑似迴圈 ${loop}、執行中 $running"
    if [ "$done_n" -lt "$want" ] && [ "$running" -eq 0 ]; then
        echo "❌ 沒跑完但也沒程序在跑 —— 中途死了，要重派"; exit 1
    fi
    [ "$done_n" -eq "$want" ] && [ "$loop" -eq 0 ] && echo "✅ 正常完成"
    ;;
dump)
    f="${2:?檔案}"; want="${3:?預期行數}"
    have=$(wc -l < "$f" 2>/dev/null || echo 0)
    echo "${f}：$have / $want 行"
    if [ "$have" -lt "$want" ]; then
        echo "❌ 行數不足 —— 很可能是逾時被砍的殘檔，不要拿去算"; exit 1
    fi
    # ⚠️ 不要用 grep -P：macOS 的 grep 不支援 PCRE，而且**不會報錯，只會都不匹配**，
    #    結果是檢查工具永遠說資料壞掉。驗證工具說謊比沒有驗證更危險。
    if ! awk 'NF{last=$0} END{exit (last ~ /\t/) ? 0 : 1}' "$f"; then
        echo "❌ 最後一行不完整"; exit 1
    fi
    echo "✅ 完整"
    ;;
esac
