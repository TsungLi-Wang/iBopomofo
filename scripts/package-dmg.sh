#!/bin/bash
# 打包發版用的 iBopomofo.dmg。
#
# 內容與歷代 release 相同：
#   安裝 i注音.app                  （iBopomofoInstaller，內含輸入法本體）
#   若 Gatekeeper 擋住請看這裡.txt   （未簽名 app 的自救說明）
#
# ⚠️ 會先跑 doc-check.sh，沒過就不打包（要跳過：DOC_CHECK_SKIP=1）。
#    理由：發版是最後一道關，版本號漂掉、文件指到不存在的檔案，
#    這時候攔下來成本最低。
#
# 用法：./scripts/package-dmg.sh [輸出路徑]
set -euo pipefail
cd "$(dirname "$0")/.."

if [ "${DOC_CHECK_SKIP:-0}" != "1" ]; then
  ./scripts/doc-check.sh || { echo "doc-check 沒過，不打包。確定要跳過就設 DOC_CHECK_SKIP=1"; exit 1; }
fi

OUT="${1:-/tmp/iBopomofo.dmg}"
DD="${DERIVED_DATA:-/tmp/ibopo-dd}"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

xcodebuild -project iBopomofo.xcodeproj -scheme iBopomofoInstaller \
  -configuration Release -derivedDataPath "$DD" build >/dev/null

APP="$DD/Build/Products/Release/iBopomofoInstaller.app"
[ -d "$APP" ] || { echo "找不到 $APP"; exit 1; }

ditto "$APP" "$STAGE/安裝 i注音.app"
cp "scripts/gatekeeper-readme.txt" "$STAGE/若 Gatekeeper 擋住請看這裡.txt"

rm -f "$OUT"
hdiutil create -volname "i注音" -srcfolder "$STAGE" -ov -format UDZO "$OUT" >/dev/null
# ⚠️ 變數後面緊接全形字元時一定要用 ${VAR} —— 不然 shell 會把全形括號
#    算進變數名，報「unbound variable」。
echo "打包完成：${OUT}（$(du -h "${OUT}" | cut -f1)）"
