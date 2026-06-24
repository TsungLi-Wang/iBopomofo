# 老王注音後續 AI 接棒 Prompt

你是老王注音 LaoWang Zhuyin 的後續協作開發 AI。這是 macOS 原生繁體中文注音輸入法，repo 為 `TsungLi-Wang/laowang-zhuyin`，目前仍保留 McBopomofo 內部 target、bundle id、input source id、C++ namespace 與安裝路徑。不要更名這些內部識別符，除非另有完整使用者資料遷移方案。

## 先讀文件

開始前必讀：

1. `AGENTS.md`
2. `algorithm.md`
3. `Source/Data/AGENTS.md`
4. 本檔

## 目前架構狀態

四層推理架構的實作進度：

- L0 即時注音引擎：維持既有 McBopomofo C++ engine，不可破壞，不可繞過 `KeyHandler` / `InputState`。
- L1 快速語義：已完成第一版候選語意重排 MVP。
- L2 深度整句校正：既有 `⌘Return` 觸發式 AI 修正仍存在，本次未重寫。
- L3 語音輸入：未實作。

Phase 狀態：

- Phase 1：部分完成。已做 ambiguity-triggered L1 候選重排：AI 命中候選清單時會把候選移到第一位；AI 回傳候選清單外結果時顯示 AI 建議並支援 Tab 採用。
- Phase 2：未做。自動 L2 尚未實作。
- Phase 3：未做。語音輸入尚未實作。
- Phase 4：未做。注音領域微調尚未實作。

## 已完成的 Phase 1 MVP

關鍵檔案：

- `Source/AICandidateReranker.swift`
- `Source/InputMethodController+AIRerank.swift`
- `Source/AICorrectionPrompt.swift`
- `Source/InputMethodController.swift`
- `Source/Preferences.swift`
- `McBopomofoTests/AICandidateRerankerTests.swift`

目前行為：

1. 使用者開候選視窗後，controller 從 `InputState.ChoosingCandidate` 擷取 top candidates。
2. 僅在 `Preferences.enableAICandidateRerank == true`、組字長度足夠、且文字含歧義字時觸發 L1。
3. 本機模型已安裝但 server 未 ready 時，背景啟動 server 並提示一次，不阻塞候選視窗。
4. server ready 時，背景呼叫本機 llama-server `/v1/chat/completions`。
5. AI 結果回到主執行緒後，檢查 serial 與 composing buffer，過期結果丟棄。
6. 如果 AI 建議命中候選清單，重建 `InputState.ChoosingCandidate` 並把該候選移到第一位。
7. 如果 AI 建議不在候選清單內，顯示 `AI Suggestion: ... (Tab)`，使用者按 Tab 採用。

## 開發約束

必須遵守：

- 不破壞 L0 注音引擎穩定性。
- 不直接從 Swift 存取或改寫 C++ engine。
- 所有按鍵仍經 `KeyHandler` / `InputState` 流程。
- `InputState` 視為不可變；若要改候選順序，重建新的 state。
- AI 呼叫必須非阻塞。
- AI 結果套用前必須檢查 composing buffer 是否仍相同。
- UI 字串使用 `NSLocalizedString`，並同步更新 `Base.lproj`、`en.lproj`、`zh-Hant.lproj`。
- 文件與註解只能使用英文或繁體中文。
- 不使用 emoji。
- 不更名 McBopomofo 內部識別符。

## 測試狀態

已驗證：

```bash
xcodebuild -project McBopomofo.xcodeproj -scheme McBopomofo -configuration Debug build
xcodebuild -project McBopomofo.xcodeproj -scheme McBopomofo -configuration Debug build-for-testing
```

兩者皆成功。

未完整驗證：

```bash
xcodebuild -project McBopomofo.xcodeproj -scheme McBopomofo -configuration Debug test
```

完整 test 曾卡在 macOS app test runner，未取得完整 pass/fail。不可宣稱完整測試全通過。

## 下一步建議

優先順序：

1. 讓 L1 觸發條件更準確：目前歧義偵測是保守字集，可加入候選差異與 reading 判斷。
2. 改善 L1 prompt golden tests：加入「水果店 + 我在去買」、「資道」、「怎摸」等案例的解析與重排驗證。
3. 做可控的 L1 開關 UI：目前只有 `Preferences.enableAICandidateRerank`，尚未掛到偏好設定視窗。
4. 解決完整 `xcodebuild test` 卡住問題，建立穩定 CI 驗證方式。
5. Phase 2 才開始做自動 L2，不要與 Phase 1 混在同一個 PR。

## 後續 AI 回覆使用者時

請用 PM 能理解的語言描述：

- L0 是原本打字引擎。
- L1 是邊打邊幫候選排序。
- L2 是按快捷鍵後整句修正。
- L3 是語音輸入。

不要只說「已完成 Phase 1-4」。目前只有 Phase 1 的 MVP 部分完成。
