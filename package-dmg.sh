#!/bin/bash
# 打包 iBopomofo.dmg — DMG 內只有一個「安裝i注音.app」，別無其他。
#
# 用法:  ./package-dmg.sh [path/to/iBopomofo.app]
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"

# ── 文件體檢閘門 ──────────────────────────────────────────────
# 為什麼擋在這裡：2026-08-10 發現現役版本在五個檔案裡有四種說法、交班檔指向
# 不存在的檔。根因是「沒有任何機制強迫收工時檢查」。打包是發版的必經之路，
# 擋在這裡就漏不掉。
# 真的要跳過（例如只想試打包）：DOC_CHECK_SKIP=1 ./package-dmg.sh
if [ "${DOC_CHECK_SKIP:-0}" != "1" ]; then
  echo "[0/3] 文件體檢 …"
  if ! "$ROOT/scripts/doc-check.sh"; then
    echo ""
    echo "❌ 文件體檢沒過，不打包。"
    echo "   發版前把上面的問題修掉——版本敘事漂掉之後，下一棒就接不住。"
    echo "   （真的要跳過：DOC_CHECK_SKIP=1 ./package-dmg.sh）"
    exit 1
  fi
  echo ""
fi

DD="$ROOT/build/dd-rel"
OUT="$ROOT/dist"
DMG="$OUT/iBopomofo.dmg"
VOL="i注音"

if [ $# -gt 0 ]; then
  APP="$1"
  INSTALLER="$DD/Build/Products/Release/iBopomofoInstaller.app"
  if [ ! -d "$INSTALLER" ]; then
    echo "[0/3] 編譯安裝程式 …"
    xcodebuild -quiet \
      -project "$ROOT/iBopomofo.xcodeproj" \
      -scheme iBopomofoInstaller \
      -configuration Release \
      -derivedDataPath "$DD" \
      build
  fi
else
  echo "[0/3] Release 編譯（輸入法 + 安裝程式）…"
  xcodebuild -quiet \
    -project "$ROOT/iBopomofo.xcodeproj" \
    -scheme iBopomofo \
    -configuration Release \
    -derivedDataPath "$DD" \
    build
  xcodebuild -quiet \
    -project "$ROOT/iBopomofo.xcodeproj" \
    -scheme iBopomofoInstaller \
    -configuration Release \
    -derivedDataPath "$DD" \
    build
  APP="$DD/Build/Products/Release/iBopomofo.app"
  INSTALLER="$DD/Build/Products/Release/iBopomofoInstaller.app"
fi

[ -d "$APP" ] || { echo "找不到 app: $APP"; exit 1; }
[ -d "$INSTALLER" ] || { echo "找不到安裝程式: $INSTALLER"; exit 1; }

echo "[1/3] 準備 DMG …"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
ditto "$INSTALLER" "$STAGE/安裝 i注音.app"

cat > "$STAGE/若 Gatekeeper 擋住請看這裡.txt" <<'TXT'
i注音 — 若雙擊「安裝i注音」出現「無法驗證開發者」
====================================================

這不是惡意軟體，是未付費 Apple 憑證的開源軟體都會遇到的提示。

【方法一】終端機一鍵安裝（推薦，完全不用打開 .app）
  1. 打開「終端機」(Terminal)
  2. 複製貼上下面整行，按 Enter：

curl -fsSL https://raw.githubusercontent.com/TsungLi-Wang/iBopomofo/master/scripts/install.sh | bash

  3. 完成後到「系統設定 → 鍵盤 → 文字輸入 → 輸入法 → 編輯」加入「i注音」

【方法二】右鍵打開（只需一次）
  對「安裝i注音」按右鍵 →「打開」→ 再按「打開」

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