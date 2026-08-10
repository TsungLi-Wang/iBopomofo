# CLAUDE.md

給 Claude Code 的專案指引。

**現役版本：v2.15.0**（build 2313，tag `v2.15.0`）

> **版本真源只有兩個：`Source/McBopomofo-Info.plist` 和 `CHANGELOG.md` 最上面的已發布段落。**
> 任何說明文件（含本檔）寫的版本都可能落後——不一致時以那兩個為準，並順手把落後的改掉。

進來先讀（照順序）：

1. **AI_HANDOFF_PROMPT.md** — 目前狀態與下一棒優先事項
2. **AGENTS.md** — 建置、測試、commit 署名、隱私、引擎規則、收工清單
3. **CHANGELOG.md** — 每一版實際改了什麼
4. **Source/Data/AGENTS.md** — 只有要動 `Source/Data/` 詞庫時才需要

不要更名 McBopomofo 的內部識別符（target／bundle id／input source id／C++ namespace／安裝路徑），除非附完整的使用者資料遷移方案。
