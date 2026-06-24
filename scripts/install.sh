#!/bin/bash
# 老王注音一鍵安裝（不需打開 .app，不受 Gatekeeper 阻擋）
#
# 用法:
#   curl -fsSL https://raw.githubusercontent.com/TsungLi-Wang/laowang-zhuyin/master/scripts/install.sh | bash
#   或在本機: ./scripts/install.sh
set -euo pipefail

REPO="TsungLi-Wang/laowang-zhuyin"
DMG_NAME="LaoWangZhuyin.dmg"
DEST="$HOME/Library/Input Methods/McBopomofo.app"
TMP="$(mktemp -d)"
MOUNT=""

cleanup() {
  if [ -n "$MOUNT" ] && [ -d "$MOUNT" ]; then
    hdiutil detach "$MOUNT" -quiet 2>/dev/null || true
  fi
  rm -rf "$TMP"
}
trap cleanup EXIT

echo "老王注音 — 安裝中（不需打開安裝程式，免 Gatekeeper）…"

DMG="$TMP/$DMG_NAME"
URL="https://github.com/$REPO/releases/latest/download/$DMG_NAME"

if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
  gh release download --repo "$REPO" --pattern "$DMG_NAME" --dir "$TMP" --clobber
else
  echo "下載 $URL …"
  curl -fL --retry 3 --progress-bar -o "$DMG" "$URL"
fi

MOUNT="$(hdiutil attach "$DMG" -nobrowse | awk '/\/Volumes\// {print $3; exit}')"
[ -n "$MOUNT" ] && [ -d "$MOUNT" ] || { echo "錯誤: 無法掛載 DMG"; exit 1; }
INSTALLER_APP="$(find "$MOUNT" -maxdepth 1 -name '*.app' ! -name '.*' | head -1)"
[ -n "$INSTALLER_APP" ] || { echo "錯誤: DMG 內找不到安裝程式"; exit 1; }

SRC="$INSTALLER_APP/Contents/Resources/McBopomofo.app"
[ -d "$SRC" ] || { echo "錯誤: 安裝套件不完整 ($SRC)"; exit 1; }

killall McBopomofo 2>/dev/null || true
rm -rf "$DEST"
ditto "$SRC" "$DEST"
xattr -dr com.apple.quarantine "$DEST" 2>/dev/null || true
"$DEST/Contents/MacOS/McBopomofo" install

VERSION="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$DEST/Contents/Info.plist" 2>/dev/null || echo '?')"
echo ""
echo "完成！老王注音 v${VERSION} 已安裝。"
echo ""
echo "請到：系統設定 → 鍵盤 → 文字輸入 → 輸入法 → 編輯"
echo "按「+」→「中文」→「老王注音」→「加入」"
echo ""

if command -v osascript >/dev/null 2>&1; then
  osascript -e 'display dialog "老王注音已安裝完成！\n\n請到「系統設定 → 鍵盤 → 文字輸入 → 輸入法 → 編輯」加入「老王注音」。" buttons {"好的"} default button 1 with title "老王注音"' 2>/dev/null || true
  if [ "$(uname -r | cut -d. -f1)" -ge 22 ] 2>/dev/null; then
    open "x-apple.systempreferences:com.apple.Keyboard-Settings.extension?InputSources" 2>/dev/null || true
  fi
fi