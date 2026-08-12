#!/bin/bash
# 清掉累積的建置產物。**只刪可再生的東西，不碰原始碼、模型、個人化資料。**
#
# ## 為什麼要有這支
#
# 2026-08-12：Johnny 的 Mac 跳出「儲存空間不足」，剩 6.6GB。
# 根因不是裝了什麼軟體，是 `build/` 底下累積了 **43 個 dd-* 建置目錄**，共 50GB。
# 每一棒為了拿乾淨的 GitRevision 戳記都用 `-derivedDataPath` 開一個新的，
# 用完沒人清 —— 一個約 1.2GB，四十幾棒就是 50GB。
#
# 規矩：**開新的 derivedDataPath 之前或收工時跑這支。**
#
# 用法：
#   ./scripts/clean-build-dirs.sh          # 列出會刪什麼，不執行（dry run）
#   ./scripts/clean-build-dirs.sh --yes    # 真的刪

set -euo pipefail
cd "$(dirname "$0")/.."
REPO="$(pwd)"

DRY=1
[ "${1:-}" = "--yes" ] && DRY=0

targets=()
[ -d "$REPO/build" ] && targets+=("$REPO/build")
[ -d "$REPO/Source/Engine/build-test" ] && targets+=("$REPO/Source/Engine/build-test")
while IFS= read -r d; do targets+=("$d"); done < <(
    find "$HOME/Library/Developer/Xcode/DerivedData" -maxdepth 1 \
        \( -name "McBopomofo-*" -o -name "iBopomofo-*" \) 2>/dev/null || true
)
while IFS= read -r d; do targets+=("$d"); done < <(
    find /tmp -maxdepth 1 \( -name "dd-*" -o -name "gate-build" -o -name "mut-build" \) 2>/dev/null || true
)

if [ ${#targets[@]} -eq 0 ]; then
    echo "沒有可清的建置產物。"
    exit 0
fi

total=0
for t in "${targets[@]}"; do
    sz=$(du -sk "$t" 2>/dev/null | awk '{print $1}') || sz=0
    total=$((total + sz))
    printf "  %-72s %6s MB\n" "$t" "$((sz / 1024))"
done
echo "──────"
echo "合計約 $((total / 1024 / 1024)) GB"

if [ "$DRY" -eq 1 ]; then
    echo ""
    echo "（這是 dry run，什麼都沒刪。要真的刪：$0 --yes）"
    exit 0
fi

for t in "${targets[@]}"; do rm -rf "$t"; done
echo ""
echo "已清除。可用空間："
df -h / | tail -1
