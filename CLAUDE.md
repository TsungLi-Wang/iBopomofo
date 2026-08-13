# CLAUDE.md

給 Claude Code 的專案指引。

> **現役版本不寫在這裡。** 看 `CHANGELOG.md` 最上面的已發布段落，或 `Source/McBopomofo-Info.plist`。
> 說明文件一律不抄版本號 —— 抄了就會漂（2026-08-10 曾漂到五個檔案四種說法）。
> 收工前跑 `./scripts/doc-check.sh` 會自動抓這類不一致。

進來先讀（照順序）：

1. **AI_HANDOFF_PROMPT.md** — 目前狀態與下一棒優先事項（一頁）
2. **docs/dead-ends.md** — 已證明無效的路，**動手前必讀**（兩頁內）
3. **AGENTS.md** — 建置、測試、commit 署名、隱私、引擎規則、收工清單
   - 「同步到 Git」→ AGENTS「同步到 Git」（commit→push→查 CI，分 Stage 回報）。
   - 「正式發布 vX.Y.Z」→ AGENTS「正式發布」（確認 plist／CHANGELOG → annotated tag → push tag → Release workflow）。**禁止**用同步動作去打 tag。
4. **CHANGELOG.md** — 每一版實際改了什麼
5. **docs/decisions/** — 為什麼這樣做、試過什麼。**要動該領域時才讀**
6. **Source/Data/AGENTS.md** — 只有要動 `Source/Data/` 詞庫時才需要

內部識別符已於 2026-08-12（棒⑥）統一為 iBopomofo：bundle id `io.ibopomofo.inputmethod.iBopomofo`、安裝路徑 `~/Library/Input Methods/iBopomofo.app`、C++ namespace `iBopomofo`、target／專案檔 `iBopomofo`。
**刻意保留舊名的三類，改到反而是錯**：上游 Copyright 署名（The McBopomofo Authors）、詞庫 on-disk 格式魔術字串（`# format org.openvanilla.mcbopomofo.sorted`）、歷史檔（`AI_HANDOFF_ARCHIVE.md`、CHANGELOG 舊版條目）。
**通則**：凡改一個字串要連帶「改讀取端＋重產資料」的，一律 KEEP —— 那不是改名，是改檔案格式。
