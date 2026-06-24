#!/bin/bash
# 把 Release 版 McBopomofo.app 與圖形化安裝程式打包成 LaoWangZhuyin.dmg。
#
# DMG 內容（標準 Mac 安裝體驗）:
#   - 安裝老王注音.app：圖形化安裝精靈（推薦）
#   - McBopomofo.app：可拖曳安裝
#   - 拖曳到這個資料夾.app：開啟 ~/Library/Input Methods
#   - 安裝說明.txt
#
# 用法:  ./package-dmg.sh [path/to/McBopomofo.app]
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
DD="$ROOT/build/dd-rel"
OUT="$ROOT/dist"
DMG="$OUT/LaoWangZhuyin.dmg"
VOL="老王注音"

if [ $# -gt 0 ]; then
  APP="$1"
  INSTALLER="$DD/Build/Products/Release/McBopomofoInstaller.app"
  if [ ! -d "$INSTALLER" ]; then
    echo "[0/5] 編譯安裝程式 …"
    xcodebuild -quiet \
      -project "$ROOT/McBopomofo.xcodeproj" \
      -scheme McBopomofoInstaller \
      -configuration Release \
      -derivedDataPath "$DD" \
      build
  fi
else
  echo "[0/5] Release 編譯（輸入法 + 安裝程式）…"
  xcodebuild -quiet \
    -project "$ROOT/McBopomofo.xcodeproj" \
    -scheme McBopomofo \
    -configuration Release \
    -derivedDataPath "$DD" \
    build
  xcodebuild -quiet \
    -project "$ROOT/McBopomofo.xcodeproj" \
    -scheme McBopomofoInstaller \
    -configuration Release \
    -derivedDataPath "$DD" \
    build
  APP="$DD/Build/Products/Release/McBopomofo.app"
  INSTALLER="$DD/Build/Products/Release/McBopomofoInstaller.app"
fi

[ -d "$APP" ] || { echo "找不到 app: $APP"; exit 1; }
[ -d "$INSTALLER" ] || { echo "找不到安裝程式: $INSTALLER"; exit 1; }

echo "[1/5] 準備暫存內容 …"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

ditto "$APP" "$STAGE/McBopomofo.app"
ditto "$INSTALLER" "$STAGE/安裝老王注音.app"

echo "[2/5] 建立「拖曳到這個資料夾」捷徑 …"
osacompile -o "$STAGE/拖曳到這個資料夾.app" "$ROOT/dmg-extras/open-input-methods-folder.applescript"

echo "[3/5] 寫入安裝說明 …"
cat > "$STAGE/安裝說明.txt" <<'TXT'
老王注音 — 安裝說明
====================

【推薦】圖形化安裝
  1. 雙擊「安裝老王注音」
  2. 若 macOS 顯示「無法驗證開發者」：對圖示按右鍵 →「打開」→ 再按「打開」
     （未付費 Apple 憑證的開源軟體都只需這一次，之後不必重複）
  3. 同意條款 → 安裝完成後，到「系統設定 → 鍵盤 → 文字輸入 → 輸入法 → 編輯」加入「老王注音」

【進階】拖曳安裝（像一般 app 一樣）
  1. 雙擊「拖曳到這個資料夾」→ Finder 會開啟輸入法安裝位置
  2. 把「McBopomofo」拖進那個資料夾
  3. 到系統設定加入「老王注音」
     （首次使用時輸入法會自動完成 macOS 安全設定，本機 AI 即可運作）

【為什麼不是拖到「應用程式」？】
  老王注音是「輸入法」，必須放在「輸入法」資料夾，而不是「應用程式」資料夾。
  這和系統內建注音、各大輸入法的安裝方式相同。

【使用】
  切到老王注音打字。組字中按 ⌘Enter 可 AI 整句修正；候選混淆時會自動 AI 重排（Tab 採用）。
  首次使用本機 AI 會自動下載模型（約 2.9GB，需連網、一次性），之後永久離線。
TXT

echo "[4/5] 產生 .dmg …"
mkdir -p "$OUT"
rm -f "$DMG"
hdiutil create -volname "$VOL" -srcfolder "$STAGE" -ov -format UDZO "$DMG" >/dev/null

echo "[5/5] 完成"
echo "輸出: $DMG"
du -h "$DMG" | awk '{print "大小:", $1}'