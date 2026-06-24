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
- L1 快速語義：Phase 1 MVP 已加強（debounce、暖機重試、候選同音觸發、選單與偏好設定開關）。
- L2 深度整句校正：既有 `⌘Return` 觸發式 AI 修正仍存在，本次未重寫。
- L3 語音輸入：未實作。

Phase 狀態：

- Phase 1：約 95% 完成。L1 候選重排 + debounce + server 重試 + 選單/偏好設定開關已完成；完整 `xcodebuild test` 已可穩定全綠並乾淨結束(見「測試狀態」),L1 觸發條件已收緊以降低過度觸發。
- Phase 2：未做。自動 L2 尚未實作。
- Phase 3：未做。語音輸入尚未實作。
- Phase 4：未做。注音領域微調尚未實作。

## 已完成的 Phase 1 工作

關鍵檔案：

- `Source/AICandidateReranker.swift`
- `Source/InputMethodController+AIRerank.swift`
- `Source/AICorrectionPrompt.swift`
- `Source/InputMethodController.swift`
- `Source/Preferences.swift`
- `McBopomofoTests/AICandidateRerankerTests.swift`

目前行為：

1. 使用者開候選視窗後，controller 從 `InputState.ChoosingCandidate` 擷取 top candidates（含注音）。
2. `needsSemanticRerank` 會在候選同音(`hasReadingCollision`)、多字候選近似同音(`hasPhraseAlternativeCollision`,只差一個音節)、或歧義字 + 多候選時觸發 L1。注意 `hasPhraseAlternativeCollision` 已從舊版「任兩個不同多字詞就觸發」收緊為「音節數相同且僅差一個音節」,避免每次多字選字都打 server。
3. 150ms debounce 後才送本機 server 請求。
4. 模型已安裝但 server 未 ready 時，背景啟動 server 並每 2 秒重試（最多 6 次）。
5. AI 結果回到主執行緒後，檢查 serial 與 composing buffer，過期結果丟棄。
6. AI 建議命中候選清單時，重建 state 並把候選移到第一位。
7. AI 建議不在候選清單內時，顯示 tooltip「AI 建議：… (Tab)」，Tab 採用。
8. 輸入法選單與偏好設定「進階」分頁可切換「AI 候選建議」。

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

單元測試（`AICandidateRerankerTests`）涵蓋 prompt、解析、觸發條件、重排邏輯。

建置：

```bash
xcodebuild -project McBopomofo.xcodeproj -scheme McBopomofo -configuration Debug build
```

完整測試（110 tests / 9 suites,約 4 秒,全綠並乾淨結束）：

```bash
xcodebuild test -project McBopomofo.xcodeproj -scheme McBopomofo -configuration Debug CODE_SIGNING_ALLOWED=NO
```

過去「完整 `xcodebuild test` 卡住」已解決,原因有二,都已修正：

1. 測試以 McBopomofo.app 當 test host 啟動,`AppDelegate.applicationDidFinishLaunching` 會 spawn 內嵌 llama-server(載 2.9GB 模型)又連網檢查更新,模型載入與背景子程序讓測試無法結束。現以 `XCTestConfigurationFilePath` 偵測測試環境,跳過這兩個副作用。
2. `VersionUpdateApiTests` 用 `withCheckedContinuation` 包 `VersionUpdateApi.check`,但本 fork 未設 `UpdateInfoEndpoint` → `check` 直接回傳 nil 而不呼叫 callback → continuation 永不 resume → 永久卡死。測試已改為判斷 `check` 回傳 nil(無端點)時視為通過。

⚠️ `VersionUpdateApi.check` 在缺少更新端點時「回傳 nil 且不呼叫 callback」是上游既有的 API 行為,目前只在測試端規避,未改動正式程式。

## 下一步建議

優先順序：

1. 觀察 L1 在真實輸入下的命中率;若仍過度觸發,進一步調整 `hasPhraseAlternativeCollision` 的「差一個音節」門檻或 `ambiguousCharacters` 範圍(`Source/AICandidateReranker.swift`)。
2. （可選）把純邏輯測試抽成不依賴 host app 的 logic test target,讓單元測試完全脫離 IMK host;目前完整 `xcodebuild test` 已可穩定執行,此項非必要。
3. Phase 2：句末自動 L2（獨立 PR）。
4. Phase 3：語音輸入（獨立 PR）。

## 後續 AI 回覆使用者時

請用 PM 能理解的語言描述：

- L0 是原本打字引擎。
- L1 是邊打邊幫候選排序。
- L2 是按快捷鍵後整句修正。
- L3 是語音輸入。

不要只說「已完成 Phase 1-4」。目前 Phase 1 約 95%（L1 已可用、完整測試已穩定），Phase 2-4 未開始。