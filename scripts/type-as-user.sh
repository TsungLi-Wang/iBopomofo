#!/bin/bash
# 把一句中文變成鍵序，實際打進已安裝的 i注音，回報實際出字。
#
# ## 為什麼要有這支
#
# 基準測試量的是「每句一個目標字、純漢字、6~24 字」—— 真實打字不是這樣。
# 而手動把中文轉成注音鍵序很容易出錯（2026-08-11 一天內轉錯三次，
# 每次都以為是引擎的 bug，其實是我鍵序打錯）。
#
# 這支自動查詞庫取得讀音、轉成鍵序、逐音節送鍵，然後把「想打的」跟
# 「實際出的」並排給你看。**當使用者用，不是當測試跑。**
#
# 用法：
#   ./scripts/type-as-user.sh "今天下午要開會討論那個提案"
#   ./scripts/type-as-user.sh -f sentences.txt     # 一行一句，批次打
#
# 需求：目前輸入法 = i注音；終端機有輔助使用權限。
set -euo pipefail
cd "$(dirname "$0")/.."

CURRENT=$(swift -e 'import Carbon; let s = TISCopyCurrentKeyboardInputSource().takeRetainedValue(); if let p = TISGetInputSourceProperty(s, kTISPropertyInputSourceID) { print(Unmanaged<CFString>.fromOpaque(p).takeUnretainedValue()) }' 2>/dev/null)
if [[ "$CURRENT" != *"iBopomofo"* ]]; then
    echo "目前輸入法不是 i注音：$CURRENT" >&2
    exit 1
fi

# ⚠️ 先重啟輸入法。
#
# e2e 測試跑在一個**長壽命的有狀態程序**上：使用者覆寫模型（UOM）會累積，
# 而且累積的狀態會改變出字。2026-08-11 就被騙過一次 —— 「他」打成「它」，
# 查了半天以為是引擎排序有問題，重啟之後就正確了。
#
# 所以每次驗證前一律重啟，讓結果是確定性的。
pkill -f "Input Methods/iBopomofo.app" 2>/dev/null || true
sleep 4

if [ "${1:-}" = "-f" ]; then
    SENTS=$(cat "$2")
else
    SENTS="${1:?用法: $0 \"中文句子\" 或 $0 -f 檔案}"
fi

# 中文 → 注音 → 美式鍵序。讀音查引擎詞庫（跟 auto_annotate.py 同一套）。
PLAN=$(python3 - "$SENTS" <<'EOF'
import sys, re, collections
DATA = "Source/Data/data.txt"
best = {}
with open(DATA, encoding="utf-8") as fh:
    for line in fh:
        if line.startswith("#"):
            continue
        p = line.split()
        if len(p) >= 3 and len(p[1]) == 1:
            r, ch, sc = p[0], p[1], float(p[2])
            if ch not in best or sc > best[ch][1]:
                best[ch] = (r, sc)

M = {'ㄅ':'1','ㄆ':'q','ㄇ':'a','ㄈ':'z','ㄉ':'2','ㄊ':'w','ㄋ':'s','ㄌ':'x',
     'ㄍ':'e','ㄎ':'d','ㄏ':'c','ㄐ':'r','ㄑ':'f','ㄒ':'v','ㄓ':'5','ㄔ':'t',
     'ㄕ':'g','ㄖ':'b','ㄗ':'y','ㄘ':'h','ㄙ':'n','ㄧ':'u','ㄨ':'j','ㄩ':'m',
     'ㄚ':'8','ㄛ':'i','ㄜ':'k','ㄝ':',','ㄞ':'9','ㄟ':'o','ㄠ':'l','ㄡ':'.',
     'ㄢ':'0','ㄣ':'p','ㄤ':';','ㄥ':'/','ㄦ':'-','ˊ':'6','ˇ':'3','ˋ':'4','˙':'7'}

for sent in sys.argv[1].split("\n"):
    sent = sent.strip()
    if not sent:
        continue
    keys, miss = [], []
    for ch in sent:
        if ch not in best:
            miss.append(ch)
            continue
        syl = best[ch][0]
        k = "".join(M.get(c, "") for c in syl)
        # 一聲沒有調號鍵，要補一個空白鍵當作「這個音節打完了」。
        # 有調號的音節則以調號鍵作結，音節之間不能再插空白 ——
        # 插了會被輸入法當成獨立的空白鍵（叫出候選窗），整句就歪掉。
        # 空白先寫成 _ ，交給 shell 端還原，避免行尾空白在 read 時被吃掉。
        keys.append(k + ("" if any(t in syl for t in "ˊˇˋ˙") else "_"))
    if miss:
        print(f"SKIP\t{sent}\t詞庫沒有：{''.join(miss)}")
    else:
        print(f"TYPE\t{sent}\t{''.join(keys)}")
EOF
)

echo "$PLAN" | while IFS=$'\t' read -r tag sent keys; do
    if [ "$tag" = "SKIP" ]; then
        printf "  ⚠️  %s（%s）\n" "$sent" "$keys"
        continue
    fi
    # 2026-08-12：原本這裡叫 /tmp/e2e_slow.sh —— 一支只存在於 /tmp 的臨時檔，
    # repo 沒有、文件沒提，重開機就被系統清掉。加上 2>/dev/null 把
    # 「command not found」吞掉，於是整輪跑完一行都不印，看起來像沒事。
    # 改成呼叫 repo 內的 e2e-typing-check.sh，別再依賴 /tmp。
    got=$(./scripts/e2e-typing-check.sh "${keys//_/ }" 6 2>/dev/null | tail -1)
    if [ "$got" = "$sent" ]; then
        printf "  ✅ %s\n" "$sent"
    else
        printf "  ❌ 想打：%s\n     實際：%s\n" "$sent" "$got"
    fi
done
