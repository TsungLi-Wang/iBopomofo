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
- Phase 2：MVP 已落地(實驗功能,預設關閉)。句末標點自動觸發 L2,第一版只提示不 commit,Tab 採用;手動 `⌘Return` 行為不變。純邏輯測試已補。尚待真機端到端驗證(打字→句末標點→跳建議→Tab 採用)。
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

## 交班日誌

### 2026-06-24T18:13:36+08:00 Phase 2 開工前判讀

使用者表示想了解 Phase 2,但暫不開工。已確認目前規劃中的 Phase 2 指「句末自動 L2」,不是重寫現有 `⌘Return` 整句修正。

目前最佳接點:

- 現有 L2 入口在 `Source/InputMethodController+AICorrection.swift` 的 `triggerAICorrection(guess:client:)`。
- 手動觸發點在 `Source/InputMethodController.swift` 的 `⌘Return` 判斷。
- AI 後端 dispatch 已集中在 `correctAIGuess(guess:preceding:backend:)`。
- 結果套用在 `applyAICorrectionResult(...)`;目前會直接清掉 `keyHandler` 並 commit 修正結果,適合手動 `⌘Return`,但不適合直接拿來做自動 L2。
- 前文擷取可繼續使用 `precedingTextForAI(from:maxChars:)`。

Phase 2 建議先做保守 MVP:

1. 新增一個自動 L2 排程層,例如 `InputMethodController+AIAutoCorrection.swift`,不要改 C++ engine,不要繞過 `KeyHandler` / `InputState`。
2. 在 `InputState.Inputting` 更新後,遇到句末標點或停頓時排程,使用 debounce,建議 800ms 到 1200ms。
3. 只在 composing buffer 長度達門檻、游標位於句尾、目前仍是 `InputState.Inputting` 時觸發。
4. AI 呼叫繼續非阻塞,並沿用 serial + composing buffer 檢查,丟棄過期結果。
5. 自動 L2 第一版不要直接 commit 修正結果;若 AI 結果不同,先顯示 tooltip 或通知,讓使用者按 Tab 或明確確認鍵採用。
6. 手動 `⌘Return` 維持現有直接套用行為;自動 L2 應拆成「取得建議」與「採用建議」兩步。
7. 新增偏好設定開關,建議命名 `enableAIAutoCorrection`,第一版可預設關閉或標為實驗功能。
8. 測試先補純邏輯:句末觸發條件、debounce/serial 過期丟棄、相同結果不提示、不同結果只建立 pending suggestion 不 commit。

主要風險:

- 若復用 `applyAICorrectionResult(...)` 直接 commit,自動 L2 可能在使用者繼續打字時誤改或搶輸入。
- 本機模型載入中時不應頻繁通知;可參考 L1 的暖機重試與只通知一次策略。
- 自動 L2 的觸發條件要比 L1 更保守,避免每個短句或半句都打本機 server。

### 2026-06-25T11:05:00+08:00 Phase 2 MVP 實作完成 + prompt 強化

兩件事在這次 session 完成:

1. **本機模型 prompt 強化(在/再、的/得/地)**:`Source/AICorrectionPrompt.swift` 的 `localSystemPrompt`(L2)與 `rerankSystemPrompt`(L1)補上同音虛字判別規則與對比例句。下手前先用同一本機 server 做 A/B 實測:新版修對「再/在」與「資道→知道」等案例、對 8 句正確句零誤改、零退步;「得/地」這類本機 4B 小模型加規則仍常漏,屬模型能力上限,留待 Phase 4 微調。

2. **Phase 2 句末自動 L2(保守 MVP)**:照本日誌前一條的設計實作,採「句末標點觸發 + 只提示不 commit + 預設關閉實驗功能」。

新增檔:
- `Source/AIAutoCorrector.swift`:純邏輯觸發層(`endsWithSentencePunctuation`、`isCorrectableSentence`、`shouldSchedule`、常數 debounce 0.8s / minComposingLength 4 / 句末標點集合 `。！？!?…`)。
- `Source/InputMethodController+AIAutoCorrection.swift`:controller 接入。debounce → 背景 `LocalServerAICorrector.correct` → 主執行緒檢查 serial 與 composingBuffer → 結果不同只 `show(tooltip:)` 並存 `aiAutoCorrectionSuggestion`,**不 commit**;`acceptAIAutoCorrectionSuggestionIfAvailable` 由 Tab 觸發才 commit。暖機重試與「只通知一次」沿用 L1 策略。
- `McBopomofoTests/AIAutoCorrectorTests.swift`:9 個純邏輯測試(句末標點偵測、長度/游標門檻、句中標點不觸發)。

改動既有檔:
- `Source/InputMethodController.swift`:新增 5 個 `aiAutoCorrection*` 狀態屬性;在 `handle(state: InputState.Inputting...)` 末尾呼叫 `scheduleAIAutoCorrectionIfNeeded`;Tab(keyCode 48)多接一條 `acceptAIAutoCorrectionSuggestionIfAvailable`;Empty / EmptyIgnoringPreviousState / Committing 三處加 `resetAIAutoCorrectionState()`;選單加「AI 句末自動校正(實驗)」;`show(tooltip:)` 由 `private` 改 internal 供擴充檔呼叫。
- `Source/Preferences.swift`:`enableAIAutoCorrection`(預設 false)+ toggle + observe/狀態列印。
- 三個 `Localizable.strings`:新增 `AI Auto-Correction (Experimental)` 與 `Local AI auto-correction is loading`。

測試:完整 `xcodebuild test` 通過,119 tests / 10 suites(原 110/9,新增 AIAutoCorrector suite)。

未完成:**真機端到端驗證尚未做**。單元測試只覆蓋純觸發邏輯;tooltip 顯示 + Tab 採用 + 句末標點是否確實進組字區,需實機開實驗開關打字驗證。下一棒接手請先做這個再考慮發版。

注意:pbxproj 既有的 `FACE0040/0041/0042` 已被 `QuarantineHelper.swift` 佔用;本次新檔改用 `FACE0050~0053`,登記新 Swift 檔時別再撞這段。
