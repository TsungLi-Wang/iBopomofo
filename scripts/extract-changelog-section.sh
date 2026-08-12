#!/usr/bin/env bash
# 從 CHANGELOG.md 抽出指定版本段落（Keep a Changelog：## [X.Y.Z] … 到下一個 ## [）。
# 用法：./scripts/extract-changelog-section.sh 2.17.0
# 只讀、不改檔。找不到段落 → exit 1。
set -euo pipefail
cd "$(dirname "$0")/.."

VER="${1:?usage: $0 X.Y.Z}"
CHANGELOG="${2:-CHANGELOG.md}"

[ -r "$CHANGELOG" ] || { echo "找不到 $CHANGELOG" >&2; exit 1; }

python3 - "$VER" "$CHANGELOG" <<'PY'
import re, sys
ver, path = sys.argv[1], sys.argv[2]
text = open(path, encoding="utf-8").read()
# Match ## [2.17.0] or ## [2.17.0] — date
pat = re.compile(
    rf"^## \[{re.escape(ver)}\][^\n]*\n(.*?)(?=^## \[|\Z)",
    re.M | re.S,
)
m = pat.search(text)
if not m:
    print(f"CHANGELOG 找不到 ## [{ver}] 段落", file=sys.stderr)
    sys.exit(1)
body = m.group(1).strip()
if not body:
    print(f"CHANGELOG ## [{ver}] 段落是空的", file=sys.stderr)
    sys.exit(1)
print(body)
PY
