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

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SELECT_SWIFT="$ROOT/scripts/select-ibopomofo-ime.swift"

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

# 2026-08-12 根因與修法（勿退回去）：
#   TISEnableInputSource 在「已經啟用」時會把前台搶成「系統設定」，
#   然後 TISSelect 選到系統設定上、TextEdit 仍是 ABC → 打出 su3cl3。
#   select-ibopomofo-ime.swift 已改成「僅在未啟用時 Enable」。
#   這裡仍：先關系統設定（若開著）→ TextEdit 前台 → 切 i注音 → 確認前台仍是
#   TextEdit 才送鍵。
osascript -e 'tell application "System Settings" to quit' >/dev/null 2>&1 || true

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
delay 0.5
EOF

# TextEdit 必須是前台時才切（TISSelect 作用在 focused app）
osascript -e 'tell application "TextEdit" to activate' >/dev/null 2>&1 || true
sleep 0.3
if ! swift "$SELECT_SWIFT" >/tmp/e2e-select-ime.log 2>&1; then
    echo "E2E: 無法切到 i注音（見 /tmp/e2e-select-ime.log）" >&2
    cat /tmp/e2e-select-ime.log >&2 || true
    exit 1
fi

# 若仍被搶焦點，立刻拉回 TextEdit（Enable 路徑已修，這是雙重保險）
FRONT=$(osascript -e 'tell application "System Events" to get name of first application process whose frontmost is true' 2>/dev/null || echo "")
if [ "$FRONT" != "TextEdit" ] && [ "$FRONT" != "文字編輯" ]; then
    osascript -e 'tell application "TextEdit" to activate' >/dev/null 2>&1 || true
    sleep 0.3
    # 拉回後再選一次（此時 Enable 不會再呼叫，只 Select）
    swift "$SELECT_SWIFT" >/dev/null 2>&1 || true
    FRONT=$(osascript -e 'tell application "System Events" to get name of first application process whose frontmost is true' 2>/dev/null || echo "")
    if [ "$FRONT" != "TextEdit" ] && [ "$FRONT" != "文字編輯" ]; then
        echo "E2E: 前台不是文字編輯（是「${FRONT}」），送鍵會打錯地方 —— 中止" >&2
        exit 1
    fi
fi

osascript <<EOF
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
