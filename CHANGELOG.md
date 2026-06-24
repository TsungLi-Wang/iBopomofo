# 版本更新歷程

本檔記錄老王注音的版本變更。格式參考 [Keep a Changelog](https://keepachangelog.com/zh-TW/1.1.0/)，版本號遵循 [語意化版本](https://semver.org/lang/zh-TW/)。

正式發佈與 DMG 下載位於 [GitHub Releases](https://github.com/TsungLi-Wang/laowang-bopomofo/releases)。

## [v1.3] - 2026-06-24

AI 後端錯誤回饋、單元測試與文案清理。

### 新增

- AI 後端改用結構化錯誤(`AICorrectionError`):修正失敗時顯示具體原因與處置建議,取代過去單一的「AI 修正失敗」。可分辨缺 API key、端點無效、逾時、連線失敗、401、429、其他 HTTP 錯誤、回應無法解析、本機 server 未就緒、codex 未登入/起不來等。
- 修正結果與原句相同時顯示「AI 未更動:整句看起來已正確」,避免按 ⌘Enter 像沒反應。
- `AICorrectionPrompt` 的 prompt 組裝、標記解析與輸出清理新增單元測試。

### 變更

- 版本紀錄從 README 拆出為獨立的 `CHANGELOG.md`。
- 使用者可見的英文文案統一為 LaoWang Bopomofo(僅顯示值,保留內部識別)。
- app 內部顯示版本由上游遺留的 `3.0` 對齊為 `1.3`(About 對話框;不影響更新檢查)。
- `package-dmg.sh` 移除對唯讀掛載來源無效的 quarantine 清除指令。

## [v1.2] - 2026-06-24

AI 架構重構與 README 產品化。

### 變更

- 將 AI 校正邏輯從 `InputMethodController.swift` 拆出；新增獨立的 prompt、Claude、Codex、本機 server corrector 檔案。
- `InputMethodController` 現在只保留觸發、狀態檢查與回填流程。
- README 重寫為正式開源產品格式，加入系統需求、安裝、AI 後端、版本更新歷程、專案結構與重構路線。
- 手動檢查更新改導向老王注音 GitHub Releases，不再導向 OpenVanilla 發佈通道。

### 清理

- 清理使用者可見的小麥注音殘留文案，安裝器與 issue template 改為老王注音語境。

## [v1.1] - 2026-06-24

本機 AI 發佈流程穩定版。

### 新增

- 本機 AI server 加入就緒狀態與暖機提示，避免模型載入中時靜默失敗。
- AI 修正加入逾時保護，避免 Claude、本機 server 或 Codex 卡住輸入流程。
- AI 修正結果回來時會檢查目前組字內容，避免過期結果覆蓋使用者新的輸入。
- 首次下載模型後加入 SHA256 完整性驗證。

### 修正

- DMG 打包腳本可直接執行，會先 Release build 再產出 `dist/LaoWangBopomofo.dmg`。
- 修正命令列 build 的 SwiftPM package 依賴解析。

## [v1.0] - 2026-06-18

注音 + 離線 AI 整句修正，首次正式 GitHub Release。

### 新增

- 本機 AI 模型改為首次使用時下載，下載後可離線使用。
- 內嵌 `llama-server` runtime，使用者不需要自行安裝 Ollama。
- DMG 內附 `安裝.command` 與安裝說明，處理未 notarize app 的 quarantine 問題。

### 變更

- 發佈包改為不內含模型，DMG 從約 2.9GB 降到約 18-19MB。

## 早期開發里程碑

正式 GitHub Release 之前的開發階段：

- 接入 AI 整句修正熱鍵（⌘Return）+ 使用者可設定金鑰／端點／模型。
- 加入 Claude、Codex、本機推理後端。
- 導入 Qwen3-4B-Instruct-2507 Q5_K_M 作為本機預設模型。
- 建立自架 DMG 打包流程。

[v1.3]: https://github.com/TsungLi-Wang/laowang-bopomofo/releases/tag/v1.3
[v1.2]: https://github.com/TsungLi-Wang/laowang-bopomofo/releases/tag/v1.2
[v1.1]: https://github.com/TsungLi-Wang/laowang-bopomofo/releases/tag/v1.1
[v1.0]: https://github.com/TsungLi-Wang/laowang-bopomofo/releases/tag/v1.0
