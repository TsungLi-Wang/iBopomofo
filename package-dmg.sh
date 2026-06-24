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

echo "[1/3] 準備 DMG（僅安裝程式）…"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
ditto "$INSTALLER" "$STAGE/安裝老王注音.app"

echo "[2/3] 產生 .dmg …"
mkdir -p "$OUT"
rm -f "$DMG"
hdiutil create -volname "$VOL" -srcfolder "$STAGE" -ov -format UDZO "$DMG" >/dev/null

echo "[3/3] 完成"
echo "輸出: $DMG"
du -h "$DMG" | awk '{print "大小:", $1}'