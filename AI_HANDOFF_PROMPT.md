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
- L1 快速語義：候選重排接縫已存在；v1.7.5 起打字當下改用進程內 n-gram scorer,不再依賴 llama-server。
- L2 深度整句校正：既有 `⌘Return` 觸發式 AI 修正仍存在，本次未重寫。
- L3 語音輸入：**已隨 v1.7 ~ v1.7.4 發佈**(Apple Speech,zh-TW on-device;**連按兩下右 Shift** push-to-talk)。IME 程序取麥克風的頭號風險已排除。v1.7.4 加「辨識來源」三選一(Apple / Apple+L2 / OpenAI Whisper 雲端)。

**目前發佈狀態:已發到 v1.7.5**(GitHub Release,Latest)。v1.7.5 = L1 即時候選重排改成本機 n-gram scorer + eval/training harness;尚未內建外部語料模型。v1.7.4 = 語音「辨識來源」三選一(Apple 原生 / Apple+L2 修正 / OpenAI Whisper 雲端,使用者自備 OpenAI key);⚠️ Whisper 錄音上傳路徑尚待更廣泛實機驗證。v1.7.3 = 辨識器自行結束(非使用者停止)時補提示、README 新增語音使用說明、清除未使用字串。v1.7.2 = 語音首次授權流程、ABC fallback、AVAudioEngine tap crash 與停止通知重疊修正。v1.7.1 = 語音熱鍵由連按兩下 Control 改連按兩下右 Shift(避開系統聽寫衝突)+ 辨識回饋。v1.7 = 在 v1.6 基礎上新增 Phase 3 語音輸入(實驗功能)。v1.6 = Phase 1(L1 候選重排)+ Phase 2(句末自動校正,實驗預設關閉)+ 強化在/再、的/得/地 prompt。完整 `xcodebuild test` 122 tests / 10 suites 全綠。

Phase 狀態：

- Phase 1：約 95% 完成。L1 候選重排 + debounce + 選單/偏好設定開關已完成；v1.7.5 起 scorer 改為本機 n-gram,不再等待 local model server。完整 `xcodebuild test` 已可穩定全綠並乾淨結束(見「測試狀態」),L1 觸發條件已收緊以降低過度觸發。
- Phase 2：MVP 已落地並隨 v1.6 發佈(實驗功能,預設關閉)。句末標點自動觸發 L2,第一版只提示不 commit,Tab 採用;手動 `⌘Return` 行為不變。純邏輯測試已補。真機已由 Johnny 確認可動。
- Phase 3：**完成並已隨 v1.7 / v1.7.1 / v1.7.2 / v1.7.3 發佈(實驗功能)**。實機驗證 IME 能取麥克風、能 on-device 辨識、能出字;push-to-talk(**連按兩下右 Shift** 開始/結束;v1.7 原為 Control,v1.7.1 改右 Shift 避開系統聽寫衝突)已實作。v1.7.2 補上首次授權兩段式流程、授權後輸入源恢復、CoreAudio tap 防 crash 與通知去重。v1.7.3 補上「辨識器自行結束時提示」(選項 b)、README 使用說明、清字串。**v1.7.4 加「辨識來源」三選一**:Apple 原生 / Apple+L2(等同「語音轉出後再過一次 L2」,已實作)/ OpenAI Whisper 雲端(使用者自備 key)。下一步可做:辨識準度/標點、選項 a 連續聆聽模式(isFinal 後自動重啟 request)、Whisper 實機驗證。詳見下方交班日誌。
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
2. `needsSemanticRerank` 會在候選同音(`hasReadingCollision`)、多字候選近似同音(`hasPhraseAlternativeCollision`,只差一個音節)、或歧義字 + 多候選時觸發 L1。注意 `hasPhraseAlternativeCollision` 已從舊版「任兩個不同多字詞就觸發」收緊為「音節數相同且僅差一個音節」,避免每次多字選字都重排。
3. 150ms debounce 後呼叫進程內 `AICandidateNGramScorer`,不再送本機 llama-server。
4. scorer 只從候選清單挑值;建議不在候選清單內就不套用,因此 L1 不生成新文字。
5. AI 結果回到主執行緒後，檢查 serial 與 composing buffer，過期結果丟棄。
6. AI 建議命中候選清單時，重建 state 並把候選移到第一位；若本來就是第一候選,只清掉提示狀態。
7. 舊的「AI 建議不在候選清單內時 tooltip + Tab 採用」路徑仍保留給防禦性分支,但 n-gram scorer 正常不會產生清單外建議。
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

完整測試（122 tests / 10 suites,全綠並乾淨結束）：

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
3. Phase 3 收尾:辨識準度/標點/口語斷句調校;語音轉出後可選再過一次 L2;或常駐聆聽模式(目前只做 push-to-talk)。
4. Rescorer 後續:補 20~50 筆 Johnny 真實錯選測資;找更貼近日常繁中輸入的可用語料,訓練外部 trigram TSV,但先不要把效果未驗證的模型包進正式版。

## 後續 AI 回覆使用者時

請用 PM 能理解的語言描述：

- L0 是原本打字引擎。
- L1 是邊打邊幫候選排序。
- L2 是按快捷鍵後整句修正。
- L3 是語音輸入。

不要只說「已完成 Phase 1-4」。目前 Phase 1/L1 已可用,Phase 2/L2 句末自動校正 MVP 已發佈但仍是實驗預設關,Phase 3/L3 語音輸入已可用且仍可調校準度/標點,Phase 4 尚未開始。

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

### 2026-06-25T11:30:00+08:00 Phase 3 設計草案(語音輸入,尚未實作,刻意先不寫程式)

Phase 3 與 L1/L2 本質不同:L1/L2 是「文字進 → 文字校正」,Phase 3 是「**語音進 → 文字出**」,不經注音鍵盤。需要麥克風擷取 + 語音轉文字(STT)。目前無既定設計。**刻意先不寫 Swift**:STT 引擎選擇會決定整個結構,先寫程式等於賭錯重寫。先把框架與決策點定清楚。

**最大技術風險(務必先驗)**:macOS 的「輸入法(input method)程序」能否取得並穩定使用麥克風授權。IME 是被系統載入的特殊程序,取麥克風的行為與一般 app 不同,有平台限制。**Phase 3 第一步應該是一個最小 spike**:在 IME 程序內試 `AVAudioEngine` 錄音 + 請求麥克風授權,確認能跑。這關不過,後面全白做。

**整合原則(沿用既有約束)**:
- 轉出的文字走現有 commit 路徑 `handle(state: InputState.Committing(poppedText:))`,不繞 `KeyHandler` / `InputState`,不直接 `insertText`。
- 不破壞 L0;語音是「另一條輸入來源」,最後匯流回同一個 commit 出口。
- 偏好 `enableVoiceInput`(預設 false,實驗);選單項;權限字串走 NSLocalizedString 三語同步。
- Info.plist 需 `NSMicrophoneUsageDescription`;若走 Apple Speech 另需 `NSSpeechRecognitionUsageDescription`。

**觸發方式建議**:push-to-talk 熱鍵(按住說話、放開轉文字)。比常駐聆聽省電、隱私好、誤觸少。常駐聆聽留待之後。

**保守 MVP(待 STT 拍板後)**:push-to-talk → on-device STT → 顯示「辨識中」狀態 → 轉出文字 commit。第一版不自動接 L2(避免雙重延遲與誤改);之後可選「語音轉出後再過一次 L2 校正」。

**地基決策(要先拍板才動程式)**:
1. **STT 引擎**(最關鍵):
   - A. **Apple Speech 框架**(`SFSpeechRecognizer`,on-device,zh-TW):系統內建、**體積零增加**、與「離線」哲學相容。風險=IME 程序能否使用、on-device 模式對 zh-TW 的支援與準度需實測。
   - B. **whisper.cpp 內嵌**(對齊現有 llama.cpp 模式):完全離線可控、架構一致(可仿 `LlamaServerManager` 做生命週期管理)。代價=再背一個 STT 模型(體積,可能又要走「首次下載」那套)、自己管程序。
   - C. **雲端 STT**:準度高、體積零;但違背「離線」哲學、要 API key/網路、有隱私考量。與本專案定位最不合。
2. **觸發**:push-to-talk 熱鍵 vs 開關常駐聆聽。
3. **麥克風授權 spike** 先做(見上「最大技術風險」)。

**建議路線**:先做 spike 驗證 IME 取麥克風可行,**同時試 A(Apple Speech)**——零體積、零下載,若 on-device zh-TW 準度堪用就定 A;不堪用再退 B(whisper.cpp 內嵌,代價是體積與下載流程,但與現有 llama 架構一致)。C 僅在前兩者都不行時考慮。

**spike 已實作(2026-06-25,Johnny 選定 A=Apple Speech)**:
- 新檔 `Source/VoiceInputManager.swift`:`@objc` 單例,`SFSpeechRecognizer(zh-TW)` + `AVAudioEngine` inputNode tap;`requestAuthorization`(Speech + `AVCaptureDevice .audio` 雙授權)、`start`/`stop`;優先 `requiresOnDeviceRecognition`;`onFinalText`/`onError` 回呼。
- `InputMethodController.swift`:選單加「語音輸入(實驗)/停止語音輸入」(標題依 `isRecording`),`toggleVoiceInput` 動作:請求授權→`start`;最終文字走 `handle(state: InputState.Committing(poppedText:))` 落地,**不繞 KeyHandler/InputState、不碰打字流程**。
- `Source/McBopomofo-Info.plist`:加 `NSMicrophoneUsageDescription` + `NSSpeechRecognitionUsageDescription`。
- 三語 strings 同步。pbxproj 用 `FACE0060/0061`。clean build 通過、119/10 測試全綠。
- **狀態:純 spike,執行期未驗證。** 編譯過 ≠ 會動。**頭號未解問題仍是「IME 程序能否取得麥克風」**,需 Johnny 實機點選單測。若 IME 拿不到麥克風,A/B/C 任何 STT 都救不了(問題在錄音不在辨識),屆時要改架構(例如獨立 helper app 錄音)。**尚未 commit / push**,等 spike 結果再決定去留。

### 2026-06-25T14:40:00+08:00 Phase 3 實機驗證通過 + push-to-talk 完成,發佈 v1.7

頭號風險「IME 程序能否取得麥克風」**已實機證實:能**。Phase 3 從 spike 升級為正式(實驗)功能並隨 v1.7 發佈。

**怎麼驗出來的(留給後人少走冤枉路)**:
- 第一次實測:點選單「語音輸入(實驗)」→ 授權通過 → 跳「聆聽中」→ 但立刻「語音辨識失敗」、字出不來。畫面通知一閃即逝,看不到真因。
- 因為錯誤被通用字串吞掉,且 IME 自身 log 在 `log stream` 裡噪音爆量(McBopomofo 程序光 idle 就數十萬行,`--level info` 更慘),**靠系統 log 撈不到**。改為在 `VoiceInputManager` 內把診斷寫進固定檔 `~/Library/Logs/laowang-voice-spike.log`(現已移除),一次定位。
- 診斷結論:`audioEngine.start()` 沒 throw、`sr=48000 ch=1` 格式合法 → **麥克風錄得到**;真正死因是 `recognitionTask` 立刻回 `kLSRErrorDomain 201: Siri and Dictation are disabled`。即 `requiresOnDeviceRecognition=true` 的離線辨識**需要系統「聽寫」開啟**(使用者開的是「語音控制 Voice Control」,那是另一套,不算)。
- 解法:Johnny 到「系統設定 ▸ 鍵盤 ▸ 聽寫」開啟聽寫(關掉 Voice Control)→ 再測 → **字正常出來,全線打通**。

**push-to-talk(連按兩下 Control)**:
- UX:原本要去選單點兩趟太蠢。改為連按兩下 Control 開始、再連按兩下 Control 結束出字。
- 為何不用 ⌘+鍵 做「按住/放開」:**macOS 在 Command 按住時會吞掉其他鍵的 keyUp**,hold-to-talk 會「按下開始、放開收不到」而停不下來。故用純修飾鍵的「連按」手勢(與系統聽寫的雙擊 Control 同理)。
- 實作在 `InputMethodController.swift`:`recognizedEvents` 本來就含 `.keyUp`/`.flagsChanged`。新增 `detectVoicePushToTalkControlDoubleTap(_:client:)` 用 flagsChanged 偵測 Control 的 rising/falling edge;只認「乾淨單擊」(兩擊間不夾其他 keyDown、不同時按其他修飾鍵),0.5s 內兩次乾淨單擊 → `toggleVoiceInput(nil)`。狀態變數 `voicePTTControlWasDown` / `voicePTTTapContaminated` / `voicePTTLastCleanTapTime`。
- 五項實測全過:啟動、出字、停止、Ctrl+C / Ctrl+V 不誤觸、正常打字不誤觸。

**收尾**:移除 spike 診斷碼(寫檔 log、buffer 計數);保留把 `kLSRErrorDomain 201` 轉成友善引導訊息「請到系統設定 ▸ 鍵盤 ▸ 聽寫 開啟」(三語 strings 已加)。版本 1.6→1.7、build 2270→2271。完整 `xcodebuild test` 全綠。

**已知限制 / 下一棒可做**:
- 觸發偵測沒有獨立單元測試(邏輯與 `NSEvent` 綁太緊);目前靠實機五項驗證。若要補,先把連按計時邏輯抽成純函式再測。
- on-device zh-TW 準度、標點、口語斷句尚未調校;`shouldReportPartialResults=false`,不顯示即時逐字。
- 正式產品化:可考慮偵測聽寫未開時主動引導、或離線不可用時退回線上辨識(需網路,與離線哲學取捨)。
- 進階:語音轉出後可選再過一次 L2 校正;常駐聆聽模式(目前只做 push-to-talk,較省電/隱私好)。

### 2026-06-25T15:30:00+08:00 v1.7.1:語音熱鍵改右 Shift + 辨識回饋

發 v1.7 後當天的體驗修正,起因是發現熱鍵衝突。

**熱鍵 Control → 右 Shift(重點)**:讀 Johnny 機器的 `defaults read com.apple.symbolichotkeys` 發現 id 164(聽寫)`enabled=1`、修飾參數 `262144`=Control、雙擊模式 → **macOS 內建聽寫的快捷鍵正是「連按兩下 Control」**,與我們的 push-to-talk 撞,兩套搶麥克風。
- 為何不改「連按三下 Control」:系統聽寫在**第 2 下就觸發**,等不到第 3 下;三下反而可能讓系統先搶走麥克風,更糟。
- 為何不靠關掉系統快捷鍵:那是使用者要記得改的系統設定,Johnny 明確不要「以後會忘記的設定」。
- 解法:改用 macOS 預設**沒有任何綁定**的「**連按兩下右 Shift**」(keyCode 60)→ 永久零衝突、零系統設定。偵測改 `detectVoicePushToTalkRightShiftDoubleTap`:用 `event.keyCode == 60` 鎖定右 Shift,沿用「乾淨單擊」判定。左 Shift(56)不觸發。
- ⚠️ 經驗:用 `event.keyCode` 區分左右修飾鍵(L/R Shift=56/60、L/R Control=59/62、L/R Option=58/61);`NSEvent.ModifierFlags` 公開列舉分不出左右。

**B 辨識回饋**:雙擊停止後 `manager.stop()` 之後到 `onFinalText` 出字之間有空窗(on-device 收尾),補「辨識中…」通知;`onFinalText` 收到空字串改提示「沒聽到內容」而非靜默。

版本 1.7→1.7.1、build 2271→2272。完整 test 全綠。發版照舊 package-dmg → push → tag v1.7.1 → gh release。pbxproj 無新檔(沿用 FACE0060/0061)。

### 2026-06-25T18:10:00+08:00 v1.7.2:語音首次授權/ABC fallback/CoreAudio crash/通知流程修正

這版是 v1.7.1 後的語音輸入穩定性與 UX patch。

**根因診斷結論**:
- 首次語音使用會出現兩個 macOS TCC 權限流程:Speech Recognition 與 Microphone。這兩個系統授權不能合併成一個 app 內彈窗;授權成功後會跨重開機保留,正常不會每次重開再問。
- 授權面板會讓 `UserNotificationCenter` 暫時成為前景,IMK 會 activate/deactivate,macOS 可能把目前輸入源暫時切到 `com.apple.keylayout.ABC`。
- 使用者最初看到「最後停在 ABC」不只是輸入源切換,真正讓它留在 ABC 的主因是 `AVAudioNode.installTap` 在某些音訊格式下丟 Objective-C exception,McBopomofo crash 後 macOS fallback 到 ABC。crash report backtrace 指向 `AVAudioEngineImpl::InstallTapOnNode`。

**本次修正**:
- 新增 `InputSourceHelper` 對 TIS current/select 的包裝,授權前只在目前輸入源確實是本 app bundle/input mode 時記住 source ID。授權完成後只在目前仍是 Apple keyboard layout 時嘗試恢復;如果使用者已切到其他第三方輸入法,不強拉回來。
- 新增 `Source/AudioTapInstaller.h/.m`,用 Objective-C `@try/@catch` 包住 `installTap`,避免 Swift 無法捕捉的 exception 直接殺掉 IME。pbxproj 新檔 ID 使用 `FACE0062~0064`。
- `VoiceInputManager.start()` 改成依序嘗試 input/output/standard/nil audio format,任何 tap 或 engine start 失敗就換下一個,最後才顯示「無法啟動麥克風」。
- 首次授權流程改成兩段式:第一次雙擊右 Shift 只要求權限;授權完成後提示「語音輸入授權完成，請再連按兩下右 Shift 開始說話」,不直接錄音。已授權後再雙擊才開始錄音。
- 停止錄音通知去重:停止時先不顯示「語音輸入已結束」;若最後沒聽到內容或錯誤,只顯示該提示;只有成功辨識並 commit 文字後才顯示「語音輸入已結束」。
- 清掉本次診斷用固定檔 log (`~/Library/Logs/laowang-voice-auth-diagnosis.log`) 與 `VoiceInputDiagnostics`,正式版不留下臨時寫檔。

**驗證**:
- Johnny 實機確認 ABC fallback 已解、語音可正常辨識。
- 完整 `xcodebuild test -project McBopomofo.xcodeproj -scheme McBopomofo -configuration Debug CODE_SIGNING_ALLOWED=NO` 通過:119 tests / 10 suites。
- 發版前另跑 Release 打包 `./package-dmg.sh`。

**後續可做**:
- 這版保留短延遲 `0.05s` 後才 `manager.start()`,只是避開同一個 key event 剛結束的邊界,不是授權延遲。若未來要再優化啟動手感,可以實測降到 0 或把啟動完成通知改成等 `audioEngine.start()` 成功後再顯示。
- 若要再診斷 IME 執行期問題,仍建議短期加固定檔 log 定位,查完務必移除;不要靠 `log stream` 撈 McBopomofo,噪音太大。

### 2026-06-26T11:00:00+08:00 v1.7.3:辨識自行結束提示(選項 b)+ README 使用說明 + 清字串

Phase 3 收尾小版。起點是 Johnny 問「辨識器自行靜默斷句結束 session」到底是什麼狀況、該怎麼處理。

**問題本質**:`SFSpeechRecognizer` 會在偵測到句尾或達到時間上限時**自行回 `isFinal`**,而使用者並沒有雙擊停止。原本程式碼此時 commit 文字 + `teardown()` 直接結束錄音,**且不發任何通知** → 使用者以為還在聽、對著已關掉的麥克風繼續講而不自知。

**當時給 Johnny 的兩個方向**:
- (a) 連續模式:isFinal 後若非使用者停止 → commit 後自動重啟一個新 request,維持 session 到使用者雙擊才停。代價:工較多、每次停頓會分段出字。
- (b) 不要再靜默:行為不變,但辨識器自行結束時補一則提示。代價小、零行為風險。

**Johnny 選 (b)**(理由:此 edge case 本就少見,先解掉最困惑的「靜默」,等真實體感再決定要不要 (a))。

**本次修改**:
- `InputMethodController.swift` 的 `manager.onFinalText` 加 `else` 分支:利用既有 `voiceInputStopNotificationPending`(只在使用者主動停止時為 true)。出字時若該旗標為 `false`,代表是辨識器自行結束,補通知「語音這段已自動結束,請再連按兩下右 Shift 重新開始」。**沒動 `VoiceInputManager`、沒碰 happy path**。
- 三語新增字串 `Voice input ended automatically. Double-tap right Shift to start again`。
- 清除三語未使用字串 `Recognizing…`(v1.7.2 通知去重時拿掉使用端、字串忘了清;已確認 swift/m/h/mm 零引用)。
- README 新增「## 語音輸入(實驗)」使用說明區段(前置開聽寫、首次兩段式授權、操作步驟、常見狀況排查);第 13 行功能 bullet 收斂並導引到該節。開發緣由(為何右 Shift、isFinal 邊界)刻意不放 README,留本檔。

**驗證**:
- `xcodebuild test -project McBopomofo.xcodeproj -scheme McBopomofo -configuration Debug CODE_SIGNING_ALLOWED=NO` 通過:119 tests / 10 suites。
- 版本 1.7.2→1.7.3、build 2273→2274。**未新增檔案,pbxproj 不動**(版本真實來源是 plist 字面值,非 pbxproj 的 `MARKETING_VERSION`)。
- 發版照舊 `./package-dmg.sh` → commit → push → tag v1.7.3 → gh release。

**後續可做**:
- 若實際長講常被自動截斷,再實作選項 (a) 連續模式。
- 「自動結束提示」這條目前無自動測試,靠實機驗;觸發偵測與通知都跟 `NSEvent` / `NotifierController` 綁緊,要測需先把判斷抽成純函式。

### 2026-06-26T12:10:00+08:00 v1.7.4:語音「辨識來源」三選一(Apple / Apple+L2 / OpenAI Whisper)

Johnny 要兩個方向:① 語音轉出後再過一次 L2、② 用 OpenAI 辨識當可選後端。收斂成**一個「語音辨識來源」選單(三選一)**,做法仿「AI 修正模型」選單。

**關鍵釐清(務必記)**:Johnny 講的「用 Codex 接語音辨識」其實**做不到**——Codex 是 OpenAI 的 coding agent CLI,不吃音訊、無 STT。OpenAI 的語音辨識是**另一條 API**(`/v1/audio/transcriptions`,whisper-1 / gpt-4o-transcribe),**必須用 OpenAI Platform 付費 API key,ChatGPT/Codex 訂閱不通用**。價格是使用者自付的事,不是我們的決策依據(Johnny 明確糾正過,別再為這種「可選的使用者自付費後端」去查價/糾結成本)。

**三來源(UserDefaults `VoiceInputSource`,預設 0)**:
- 0 = Apple 原生(離線,即原行為)。
- 1 = Apple + L2:Apple 辨識文字 → `correctVoiceText`(過目前選的 AI 後端)→ 出字。L2 任何失敗(後端未就緒/錯誤/空)都退回原文,不卡語音。等同「語音轉出後再過一次 L2」。
- 2 = OpenAI Whisper:新 `WhisperVoiceInputManager`(錄音 tap 寫 WAV 暫存,停止後讀檔)+ `WhisperVoiceTranscriber`(multipart POST `/v1/audio/transcriptions`,Bearer key,`language=zh`,回 `text`,過 OpenCC 轉繁)。只需麥克風授權,不需 Speech 授權/系統聽寫。

**架構**:`toggleVoiceInput` 依來源分流 start/stop;Apple 路徑(0/1)沿用 `VoiceInputManager`,Whisper 路徑(2)用 `WhisperVoiceInputManager`;`commitVoiceRecognizedText` 共用(含 stop vs 自動結束去重)。OpenAI key 走 `AIKeychain`(已泛化成多帳號:`ClaudeAPIKey` / `OpenAIAPIKey`),設定視窗加兩欄(key + 模型,模型預設 `whisper-1`,想換 gpt-4o-transcribe 自填)。新檔 pbxproj 用 `FACE0070~0073`。

**驗證**:`xcodebuild test` 119/10 全綠。版本 1.7.3→1.7.4、build 2274→2275。發版 `package-dmg.sh` → commit → push → tag v1.7.4 → gh release(Latest)。
**⚠️ 未實機驗證**:選項 2/3 的執行期(尤其 Whisper 錄 WAV→上傳)在開發機沒法測麥克風/打 OpenAI,只證明編譯+不破壞既有。錄音用 `AudioTapInstaller` 安全包裝 + 失敗退場,但能否真的錄到、上傳成功要 Johnny 實機收。WAV 用 tap buffer 原生格式(float32)寫,若 OpenAI 對 float wav 有問題,改成轉 16-bit PCM。

### 2026-06-26T14:00:00+08:00 AI rescorer 重構 階段一+二v1(探勘 + baseline + 字元 n-gram 第一版)

新方向(Johnny 規格):把智慧從「⌘Return 整句事後重寫」搬到「打字當下即時重排序」。完整交接以本檔最新尾段為準。
- 探勘關鍵:引擎純 unigram、`walk()` 只給 top-1 無 N-best;**L1 重排接縫已存在且已是「只重排不生成」(`InputMethodController+AIRerank.swift` / `AICandidateReranker.swift`),差別只在打分器是 4B**。任務 = 換成輕量 n-gram,非從零蓋。
- `Source/Engine/eval/`(rerank_eval.cpp + build-and-run.sh):獨立編譯、載真實 data.txt、量 walk top-1。baseline 7/8。
- 階段二 v1:字元 bigram 從 data.txt 詞頻推(零外部語料),rescore 只在 `node->unigrams()` 合法候選裡用左右文重挑。修好「意→一」、0 退步,但「在→再」翻不動(詞庫 bigram 太弱)→ **下一步換真語料 trigram(KenLM)+ 接進 AICandidateReranker**。
- 這批是 eval scaffold,**未碰引擎、未碰 app、無版本變動**。

#### 下一棒接手指南(rescorer 階段二續做)

**一句話目標**:把智慧從「⌘Return 整句事後重寫」搬到「打字當下即時重排序」;rescorer **只在引擎已產生的合法候選裡重挑,絕不生成**(根除「AI 改你原意」)。

**下一步(依優先序)**:
1. **補真實測資**:跟 Johnny 要 20~50 筆他真實會打、常選錯的句子放進 harness(8 筆太少、無統計意義)。
2. **換真語料 trigram(翻硬同音字的關鍵)**:用公開繁中語料(維基/政府開放資料/新聞)訓練 KenLM 或等價純 C++ trigram,取代目前的詞庫 bigram(詞庫 bigram 對「在/再」先天無力,已驗)。對齊可用 `Source/Data/curation/` + `count_occurrences.py` + BPMFMappings(漢字→注音)。進程內、低延遲、**不准用 llama-server**。
3. **接進活的輸入法**:把 n-gram 打分器接到 `AICandidateReranker`(取代/前置於 llama 呼叫)。整合進 app build(pbxproj 新檔別撞號,已用到 FACE0073,新檔從 FACE0074+;先 `xcodebuild test -scheme McBopomofo` 確保 119/10 不破壞)。
4. **before/after 用 harness 量**,沒有數字提升不算完成(Johnny 硬性要求)。

**護欄**:rescorer 只重排不生成;即時層不用 llama/生成式;⌘Return 的 4B/Claude/Codex 路徑保留當備援+語音後修、本次不改;**不做內部更名**(bundle id/input source id/module/資料路徑的 McBopomofo 命名別碰);改引擎前先有 baseline 數字;commit 用筆名 `老王 LaoWang <laowang@users.noreply.github.com>`。

**平行待辦(別跟 rescorer 混做)**:使用者第二半痛點「被迫接受詞組、想逐字自選」→ 現成解 = libchewing Simple mode(關自動組詞+穩定候選排序),等 rescorer 穩了再單獨評估。

**參考**:vChewing 技術白皮書(McBopomofo 的 fork,逐模組對照,The Unlicense)`https://vchewing.github.io/TechnicalWhitePaper.html`。

### 2026-06-26T15:30:00+08:00 v1.7.5:rescorer 階段收斂 + 本機 n-gram L1

Johnny 決定今天先不再卡在會考/題庫語料清理,把已完成的階段整理、commit、發佈。這版定位是 **rescorer 架構階段版**,不是「語料模型已調到最好」。

**本次落地**:
- `AICandidateReranker` 的 L1 即時重排改成進程內 `AICandidateNGramScorer`,不再等 local model server、不再呼叫 llama。鐵則維持:只重排既有候選,不生成新內容。
- `AICandidateRerankContext` 新增 `cursorIndex`,scorer 會在 composing buffer 中替換目前候選的位置後評分。
- `Source/Engine/eval/cases.tsv` 把 seed cases 外部化;`rerank_eval.cpp` 可吃外部 TSV 模型;`train_char_ngram.py` 可從純文字 / `.bz2` 維基 dump 訓練 char unigram/bigram/trigram TSV;`fetch_zhwiki_corpus.sh` 支援下載續傳中文維基 dump。
- app 若找不到 bundled `rescorer-char-ngrams.tsv`,會退回從既有 `data.txt` 建小型 fallback model。**本次沒有把維基或題庫模型包進 app**。

**實驗結果**:
- 預設 fallback:baseline 7/8,rescored 7/8。
- 用 `cases.tsv` 自己訓練的 overfit smoke-test model 可跑到 8/8,只證明 pipeline 通,不算有效指標。
- 部分中文維基 dump 約 298MB 已可用;10M / 50M 字模型都能訓練與評測,但 seed cases 仍是 baseline 7/8,rescored 7/8。50M 模型能修「意次→一次」,但「在→再」仍翻不動。原因不是工具不能跑,而是維基語域對「再說一次」這類口語輸入訊號不足。

**下一步**:
1. 優先要 Johnny 真實錯選句 20~50 筆,不要再只靠 8 筆 seed cases 判斷。
2. 語料方向先找更貼近日常台灣繁中輸入的開放文本;教育部/考題 PDF 可當候選,但清理成本高、授權也要查,不應卡住主線。
3. 只有當外部模型在真實 cases 有明確 before/after 提升,才把 `rescorer-char-ngrams.tsv` 納入 bundle / pbxproj。

**驗證**:`xcodebuild test` 122/10 全綠;eval harness 可跑預設 cases 與外部 TSV model。版本 1.7.4→1.7.5、build 2275→2276。
