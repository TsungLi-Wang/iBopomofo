#!/bin/bash
# 文件體檢：抓「文件說的」跟「實際的」不一致。
#
# 為什麼有這支：2026-08-10 派一個沒有前文的 AI 讀交接文件，發現現役版本在
# 五個檔案裡有四種說法、交班檔指向不存在的檔、Key Files 列了已刪除的程式檔。
# 那些全都是機器兩秒就能抓到的東西，不該靠派 AI 稽核才發現。
#
# 用法：./scripts/doc-check.sh        （有問題回傳 1）
# 建議時機：收工前、發版前。

set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
exec python3 scripts/doc_check.py "$@"
