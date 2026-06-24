#!/bin/bash
# 打包 LaoWangZhuyin.dmg — DMG 內只有一個「安裝老王注音.app」，別無其他。
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
    echo "[0/3] 編譯安裝程式 …"
    xcodebuild -quiet \
      -project "$ROOT/McBopomofo.xcodeproj" \
      -scheme McBopomofoInstaller \
      -configuration Release \
      -derivedDataPath "$DD" \
      build
  fi
else
  echo "[0/3] Release 編譯（輸入法 + 安裝程式）…"
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

echo "[1/3] 準備 DMG …"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
ditto "$INSTALLER" "$STAGE/安裝老王注音.app"

cat > "$STAGE/若 Gatekeeper 擋住請看這裡.txt" <<'TXT'
老王注音 — 若雙擊「安裝老王注音」出現「無法驗證開發者」
====================================================

這不是惡意軟體，是未付費 Apple 憑證的開源軟體都會遇到的提示。

【方法一】終端機一鍵安裝（推薦，完全不用打開 .app）
  1. 打開「終端機」(Terminal)
  2. 複製貼上下面整行，按 Enter：

curl -fsSL https://raw.githubusercontent.com/TsungLi-Wang/laowang-zhuyin/master/scripts/install.sh | bash

  3. 完成後到「系統設定 → 鍵盤 → 文字輸入 → 輸入法 → 編輯」加入「老王注音」

【方法二】右鍵打開（只需一次）
  對「安裝老王注音」按右鍵 →「打開」→ 再按「打開」

【永久解法】
  需開發者付費加入 Apple Developer 並 notarize，目前尚未實作。
TXT

echo "[2/3] 產生 .dmg …"
mkdir -p "$OUT"
rm -f "$DMG"
hdiutil create -volname "$VOL" -srcfolder "$STAGE" -ov -format UDZO "$DMG" >/dev/null

echo "[3/3] 完成"
echo "輸出: $DMG"
du -h "$DMG" | awk '{print "大小:", $1}'