#!/bin/bash
# 實機端到端打字驗證:把美式鍵序送進已安裝的老王注音,回報實際 commit 的文字。
# 用法: ./scripts/e2e-typing-check.sh "a04a042k7y.3eji4x96"   # 慢慢的走過來
# 完整說明(注音→鍵序對照、原理、陷阱): docs/e2e-typing-verification.md
#
# 鐵則:用 key code 不用 keystroke(keystroke 的數字鍵事件輸入法吃不到聲調)。
# 需求:目前輸入法 = 老王注音;終端機有輔助使用權限。會短暫開啟 TextEdit,
# 結束時自動關閉不存檔。

set -euo pipefail

KEYS="${1:?用法: $0 <美式鍵序,如 ql32k7cp3dj94>}"
WAIT="${2:-4}"  # 打完到 commit 的等待秒數(延遲重審需 debounce 0.6s + 打分 1-2s)

# 確認輸入法
CURRENT=$(swift -e 'import Carbon; let s = TISCopyCurrentKeyboardInputSource().takeRetainedValue(); if let p = TISGetInputSourceProperty(s, kTISPropertyInputSourceID) { print(Unmanaged<CFString>.fromOpaque(p).takeUnretainedValue()) }' 2>/dev/null)
if [[ "$CURRENT" != *"McBopomofo"* ]]; then
    echo "目前輸入法不是老王注音: $CURRENT" >&2
    echo "請先切換輸入法再跑。" >&2
    exit 1
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

osascript <<EOF
tell application "TextEdit"
    activate
    make new document
end tell
delay 1.5
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
