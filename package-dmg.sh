#!/bin/bash
# 把已編好的 McBopomofo.app(含內嵌 4B runtime)打包成可上自架站下載的 .dmg。
#
# 因為沒有 Apple Developer 帳號、不做 notarize:下載的 app 會被 macOS 標 quarantine,
# 直接雙擊會被 Gatekeeper 擋、且內嵌 llama-server 會被連坐封鎖。所以 dmg 內附:
#   - 安裝.command:一鍵清 quarantine + 複製到 ~/Library/Input Methods
#   - 安裝說明.txt:手動 Terminal 指令(最可靠的退路)
#
# 用法:  ./package-dmg.sh [path/to/McBopomofo.app]
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
APP="${1:-$ROOT/build/dd-rel/Build/Products/Release/McBopomofo.app}"
VOL="老王注音"
OUT="$ROOT/dist"
DMG="$OUT/LaoWangBopomofo.dmg"

[ -d "$APP" ] || { echo "找不到 app:$APP(先用 Release 編譯)"; exit 1; }

echo "[1/4] 準備暫存內容 …"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
ditto "$APP" "$STAGE/McBopomofo.app"

echo "[2/4] 寫入安裝器與說明 …"
cat > "$STAGE/安裝.command" <<'CMD'
#!/bin/bash
DIR="$(cd "$(dirname "$0")" && pwd)"
APP="$DIR/McBopomofo.app"
DEST="$HOME/Library/Input Methods/McBopomofo.app"
echo "安裝老王注音中 …"
xattr -dr com.apple.quarantine "$APP" 2>/dev/null || true
killall McBopomofo 2>/dev/null || true
rm -rf "$DEST"
ditto "$APP" "$DEST"
xattr -dr com.apple.quarantine "$DEST" 2>/dev/null || true
osascript -e 'display dialog "老王注音已安裝完成!\n\n請到 系統設定 → 鍵盤 → 文字輸入 → 輸入法 → 編輯,加入「老王注音」即可使用。\n\n首次按 ⌘Enter 觸發 AI 修正時,需等約 3 秒載入本機模型,之後約 0.2 秒。" buttons {"好的"} default button 1 with title "老王注音"'
CMD
chmod +x "$STAGE/安裝.command"

cat > "$STAGE/安裝說明.txt" <<'TXT'
老王注音 — 安裝說明
====================

老王注音內建離線 AI 整句修正(不必裝 Ollama、不必連網)。
因為沒有 Apple 付費憑證,從網路下載需要一個步驟解除 macOS 的安全隔離。

【方法 A:一鍵安裝(推薦)】
  1. 對著本視窗裡的「安裝.command」按右鍵 →「打開」→ 再按一次「打開」。
     (第一次會跳安全警告,選「打開」即可;之後它會自動安裝。)
  2. 依提示到「系統設定 → 鍵盤 → 輸入法」加入「老王注音」。

【方法 B:手動(最可靠)】
  打開「終端機」(Terminal),貼上這一行後按 Enter:

  xattr -dr com.apple.quarantine "/Volumes/老王注音/McBopomofo.app" && ditto "/Volumes/老王注音/McBopomofo.app" ~/Library/Input\ Methods/McBopomofo.app && xattr -dr com.apple.quarantine ~/Library/Input\ Methods/McBopomofo.app && echo "完成!請到系統設定加入老王注音"

  然後到「系統設定 → 鍵盤 → 文字輸入 → 輸入法 → 編輯」加入「老王注音」。

【使用】
  切到老王注音,打注音、組字中(底線狀態)按 ⌘Enter,AI 會把整句修正。
  首次約 3 秒(載入本機模型),之後約 0.2 秒。
  選單「AI 修正模型」預設「本機 AI(內建・離線)」;也可切 Claude 等雲端後端。
TXT

echo "[3/4] 產生 .dmg …"
mkdir -p "$OUT"
rm -f "$DMG"
hdiutil create -volname "$VOL" -srcfolder "$STAGE" -ov -format UDZO "$DMG" >/dev/null

echo "[4/4] 完成"
echo "輸出:$DMG"
du -h "$DMG" | awk '{print "大小:",$1}'
