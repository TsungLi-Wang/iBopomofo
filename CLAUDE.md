# CLAUDE.md

給 Claude Code 的專案指引。

> **現役版本不寫在這裡。** 看 `CHANGELOG.md` 最上面的已發布段落，或 `Source/McBopomofo-Info.plist`。
> 說明文件一律不抄版本號 —— 抄了就會漂（2026-08-10 曾漂到五個檔案四種說法）。
> 收工前跑 `./scripts/doc-check.sh` 會自動抓這類不一致。

進來先讀（照順序）：

1. **AI_HANDOFF_PROMPT.md** — 目前狀態與下一棒優先事項
2. **AGENTS.md** — 建置、測試、commit 署名、隱私、引擎規則、收工清單
   - Johnny 說「同步到 Git」時照 **AGENTS.md「同步到 Git」節**做：commit → push → 查 CI，**分 Stage 1/2/3 回報**；push 成功不等於 CI 通過。發布（tag／DMG）本階段未自動化。
3. **CHANGELOG.md** — 每一版實際改了什麼
4. **Source/Data/AGENTS.md** — 只有要動 `Source/Data/` 詞庫時才需要

內部識別符已於 2026-08-12（棒⑥）統一為 iBopomofo：bundle id `io.ibopomofo.inputmethod.iBopomofo`、安裝路徑 `~/Library/Input Methods/iBopomofo.app`、C++ namespace `iBopomofo`、target／專案檔 `iBopomofo`。
**刻意保留舊名的三類，改到反而是錯**：上游 Copyright 署名（The McBopomofo Authors）、詞庫 on-disk 格式魔術字串（`# format org.openvanilla.mcbopomofo.sorted`）、歷史檔（`AI_HANDOFF_ARCHIVE.md`、CHANGELOG 舊版條目）。
**通則**：凡改一個字串要連帶「改讀取端＋重產資料」的，一律 KEEP —— 那不是改名，是改檔案格式。
