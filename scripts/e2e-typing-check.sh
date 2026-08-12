#!/bin/bash
# 實機端到端打字驗證:把美式鍵序送進已安裝的i注音,回報實際 commit 的文字。
# 用法: ./scripts/e2e-typing-check.sh "a04a042k7y.3eji4x96"   # 慢慢的走過來
# 完整說明(注音→鍵序對照、原理、陷阱): docs/e2e-typing-verification.md
#
# 鐵則:用 key code 不用 keystroke(keystroke 的數字鍵事件輸入法吃不到聲調)。
# 需求:目前輸入法 = i注音;終端機有輔助使用權限。會短暫開啟 TextEdit,
# 結束時自動關閉不存檔。

set -euo pipefail

KEYS="${1:?用法: $0 <美式鍵序,如 ql32k7cp3dj94>}"
WAIT="${2:-4}"  # 打完到 commit 的等待秒數(延遲重審需 debounce 0.6s + 打分 1-2s)

# 主動切到 i注音（不要求「跑腳本的 App」當前已是 i注音 —— 依 App 記輸入法時會誤判）。
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [ -f "$ROOT/scripts/select-ibopomofo-ime.swift" ]; then
    swift "$ROOT/scripts/select-ibopomofo-ime.swift" >/dev/null 2>&1 || true
fi

# 美式鍵 → ANSI 虛擬鍵碼
CODES=$(python3 - "$KEYS" <<'EOF'
import sys
keymap = {
    'a':0,'s':1,'d':2,'f':3,'h':4,'g':5,'z':6,'x':7,'c':8,'v':9,'b':11,'q':12,
    'w':13,'e':14,'r':15,'y':16,'t':17,'1':18,'2':19,'3':20,'4':21,'6':22,
    '5':23,'=':24,'9':25,'7':26,'-':27,'8':28,'0':29,']':30,'o':31,'u':32,
    '[':33,'i':34,'p':35,'l':37,'j':38,"'":39,'k':40,';':41,'\\':42,',':43,
    '/':44,'n':45,'m':46,'.':47,' ':49,
}
try:
    print(", ".join(str(keymap[ch]) for ch in sys.argv[1]))
except KeyError as e:
    sys.exit(f"無法對應的鍵: {e}")
EOF
)

# 整段放在同一個 osascript：TextEdit 前台 → do shell script 切 i注音 → 立刻送鍵。
# （「依 App 記輸入法」時，在終端機 process 裡 TISSelect 只影響終端機，
#  2026-08-12 實測會打出 su3cl3 這種「當英文鍵」的結果。）
SELECT_SWIFT="$ROOT/scripts/select-ibopomofo-ime.swift"
osascript <<EOF
tell application "TextEdit"
    activate
    -- 先關掉所有既有文件再開新的。
    -- 2026-08-12：TextEdit 若已有開著的文件，下面讀 document 1 會把舊內容一起讀回來，
    -- 於是「實際出字」憑空多出上一輪的句子，而且看起來像引擎在亂吐字。
    repeat with i from (count documents) to 1 by -1
        close document i saving no
    end repeat
    make new document
end tell
delay 0.6
-- TextEdit 仍是前台時切輸入法（do shell script 通常不搶焦點）
try
    do shell script "swift " & quoted form of "$SELECT_SWIFT"
end try
delay 0.4
tell application "TextEdit" to activate
delay 0.2
tell application "System Events"
    key code {$CODES}
end tell
delay $WAIT
tell application "System Events" to key code 36
delay 0.5
tell application "TextEdit"
    set docText to text of document 1
    close document 1 saving no
end tell
return docText
EOF
