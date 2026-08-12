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

# 等它自己回來，不要固定 sleep。2026-08-12 實測：固定 sleep 4 之後第一句
# 打出空字串（輸入法還沒接手），而空字串會被報成「出字不對」——
# harness 沒準備好被誤判成引擎錯誤，正是這支腳本最該避免的事。
for _ in $(seq 1 30); do
    if pgrep -f "Input Methods/iBopomofo.app" >/dev/null 2>&1; then
        break
    fi
    sleep 1
done
sleep 2   # 起來之後再給它一點時間完成 IMK 連線

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

# ⚠️ 不要寫成 `echo "$PLAN" | while …`。
# 2026-08-12：原本就是那樣寫的 —— pipeline 的右邊在 subshell 裡跑，
# 迴圈內累積的失敗數出不來，整支永遠 exit 0。「全部打錯」跟「全部打對」
# 對 CI 或呼叫端來說一模一樣。改用 here-string，讓計數留在本 shell。
fail=0
pass=0
skip=0
while IFS=$'\t' read -r tag sent keys; do
    [ -z "${tag:-}" ] && continue
    if [ "$tag" = "SKIP" ]; then
        printf "  ⚠️  %s（%s）\n" "$sent" "$keys"
        skip=$((skip + 1))
        continue
    fi
    # 2026-08-12：原本這裡叫 /tmp/e2e_slow.sh —— 一支只存在於 /tmp 的臨時檔，
    # repo 沒有、文件沒提，重開機就被系統清掉。加上 2>/dev/null 把
    # 「command not found」吞掉，於是整輪跑完一行都不印，看起來像沒事。
    # 改成呼叫 repo 內的 e2e-typing-check.sh，別再依賴 /tmp。
    # 每一句都重新確認輸入法還在 i注音。
    # 2026-08-12：原本只在腳本最開頭檢查一次 —— 而檢查完的下一件事就是 pkill 輸入法。
    # 重啟後系統可能把當前輸入法掉回 ABC（實測會），腳本毫不知情繼續送鍵，
    # 於是後面每一句都回空字串，看起來像引擎壞了。這是今天最會騙人的一個。
    cur=$(swift -e 'import Carbon; let s = TISCopyCurrentKeyboardInputSource().takeRetainedValue(); if let p = TISGetInputSourceProperty(s, kTISPropertyInputSourceID) { print(Unmanaged<CFString>.fromOpaque(p).takeUnretainedValue()) }' 2>/dev/null || true)
    if [[ "$cur" != *"iBopomofo"* ]]; then
        echo ""
        echo "  ⛔ 中途輸入法掉了：$cur"
        echo "     已完成 $((pass + fail)) 句，後面沒有跑。請把輸入法切回 i注音再重跑。"
        echo "     （macOS 對「一個登入階段內能砍幾次輸入法」有上限；今天砍太多次就會這樣，"
        echo "       登出再登入可復原。）"
        echo "TYPE_AS_USER=FAIL(input source lost mid-run)"
        exit 1
    fi

    # `|| true`：單句的送鍵失敗不該讓整輪中斷（set -e + pipefail 會殺掉迴圈，
    # 於是後面的句子連跑都沒跑到，卻只看到前面幾行輸出）。失敗會在下面被算成 ❌。
    got=$(./scripts/e2e-typing-check.sh "${keys//_/ }" 6 2>/dev/null | tail -1 || true)

    # 空字串＝一個字都沒進去，那是 harness 沒送到鍵，不是引擎選錯字。
    # 2026-08-12 實測三輪：空輸出出現的位置隨機（第一句、最後兩句都發生過），
    # 而真正的出字錯誤（坐→做）三輪都在同一句。把兩者混為一談，這一關就會
    # 隨機紅燈，然後沒有人相信它。空的重打一次；再空才算失敗，並標明是送鍵問題。
    if [ -z "$got" ]; then
        sleep 3
        got=$(./scripts/e2e-typing-check.sh "${keys//_/ }" 8 2>/dev/null | tail -1 || true)
    fi
    if [ "$got" = "$sent" ]; then
        printf "  ✅ %s\n" "$sent"
        pass=$((pass + 1))
    else
        if [ -z "$got" ]; then
            printf "  ❌ 想打：%s\n     實際：（重試後仍為空 —— 送鍵沒進去，不是引擎選錯字）\n" "$sent"
        else
            printf "  ❌ 想打：%s\n     實際：%s\n" "$sent" "$got"
        fi
        fail=$((fail + 1))
    fi
done <<< "$PLAN"

echo ""
echo "=== 結果 ==="
# ⚠️ 一定要 ${} 包起來：全形「／」會被 bash 3.2 吃進變數名（unbound variable）。
echo "通過 ${pass}／失敗 ${fail}／跳過 ${skip}"
if [ "$fail" -gt 0 ]; then
    echo "TYPE_AS_USER=FAIL($fail)"
    exit 1
fi
if [ "$pass" -eq 0 ]; then
    # 一句都沒真的打到 —— 這是「安靜地什麼都沒驗」的那種壞法，不准當成功。
    echo "TYPE_AS_USER=FAIL(no sentences actually typed)"
    exit 1
fi
echo "TYPE_AS_USER=PASS"
