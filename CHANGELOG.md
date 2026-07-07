# 版本更新歷程

本檔記錄老王注音的版本變更。格式參考 [Keep a Changelog](https://keepachangelog.com/zh-TW/1.1.0/)，版本號遵循 [語意化版本](https://semver.org/lang/zh-TW/)。

正式發佈與 DMG 下載位於 [GitHub Releases](https://github.com/TsungLi-Wang/laowang-zhuyin/releases)。

## [Unreleased]

### 文件

- **在/再 real eval 收集管線就緒**：新增 `Source/Engine/eval/real-zai-eval.tsv`（真實錯選句收集檔，格式與填寫規則在檔頭註解，已預放首筆已知 miss「我再說一次」），`eval/README.md` 新增 Real eval 節記錄轉換與跑分指令；已用出貨的 `Source/Data/confusion-pairs.tsv` 驗證整條管線（首筆 baseline/disambiguated 皆 0/1，與已知行為一致）。

## [v1.9.1] - 2026-07-06

### 修正

- **消歧查表載入防呆**：`ConfusionPairDisambiguator::load` 的數值解析由 `std::stod` 改為不丟例外的嚴格解析（整欄需為有限數值），格式壞掉的行直接略過。載入發生在 `KeyHandler` 初始化，先前表檔若有一行毀損會讓輸入法啟動即崩潰；現在最壞情況只是該行證據失效。補 2 個壞表 gtest。（源自新酷音 Rust 重寫回顧一文的 fuzzing 邊界教訓）

## [v1.9.0] - 2026-07-06

「在/再」智慧消歧模組首次隨版內建（實驗功能，預設關閉）。開啟輸入法選單「同音字智慧消歧（實驗）」後，打字當下引擎會用左右文機率查表，把選錯的「在/再」就地改選——已實機驗證「我再問一次」「做完再弄」等句正確翻轉、「我在家等你」不誤翻。保守設計：證據不足時維持引擎原判（例如「我再說一次」目前不翻，待真實語料校準）。

### 新增

- **「在/再」智慧消歧模組（引擎節點覆寫 Phase A，實驗，預設關）**：新增 `ConfusionPairDisambiguator`（C++，`Source/Engine/`），在每次 lattice walk 之後，對讀音含 ㄗㄞˋ 的節點用「左右鄰字 log-odds 查表」重新在**節點內既有 unigram** 裡挑字——覆蓋單字節點（在/再）與詞典孿生詞節點（我在/我再），採 soft override（`kOverrideValueWithScoreFromTopUnigram`），不改切詞、不生成新字、不進使用者覆寫模型（override-without-observe，見 `docs/engine-node-override.md`）；使用者手動選字與 UOM 建議永遠優先。掛點在 `KeyHandler.mm` 的 `_walk`，由實驗偏好「同音字智慧消歧（實驗）」控制（預設關），且需 bundle 內存在 `confusion-pairs.tsv` 查表檔才生效（本版未附表，等真實語料訓練並通過 real eval 才會內建）。查表框架對其他混淆對（的/得/地、做/作…）開放。
- **建表與驗證工具**：`Source/Engine/eval/build_confusion_pair_table.py`（從語料統計左右鄰字 log-odds，含人工 review 清單與 coverage）、`masked_eval_confusion_pair.py`（遮蔽測試 + threshold sweep）；`rerank_eval` harness 新增第三條「disambiguated」線，直接量正式出貨路徑。合成語料 smoke 數字：遮蔽測試 baseline 50% → 查表 95%；引擎級整句 40/99 → 75/99、零退步。
- C++ gtest 新增 `ConfusionPairDisambiguatorTest`（10 tests：翻轉、孿生詞節點、尊重使用者覆寫、上下文變更撤回、soft override 不影響路徑分數等）。

### 變更

- **「在/再」查表已內建（`Source/Data/confusion-pairs.tsv`）**：v2 正式表（680 句訓練、threshold 0.5、524 條）已加入 McBopomofo target Resources，安裝後開啟實驗偏好「同音字智慧消歧（實驗）」即可使用；預設仍關閉，不影響既有行為。真實錯選句 real eval 仍待收集，用於後續校準門檻與語料。
- **建表腳本方法修正 + v2 語料訓練完成**：`build_confusion_pair_table.py` 的 L/R 證據改為類別條件似然比（合成語料的在/再配比不再滲入證據），prior 改可從引擎詞典推導（`--prior-from-data`，在/再為 -0.912，天然偏「在」）。以 v2 合成語料（600 句、12 類含陷阱類）+ 舊語料共 680 句訓出正式表（threshold 0.5、524 條、8.2KB）：留出集翻「再」精確率 90.3%、舊 eval 零誤翻；引擎級「在/再字位」56/120 → 70/120（修對 15、改壞 1）。表尚未進 bundle，待真實錯選句 eval 或使用者拍板。數字與重跑指令見 `Source/Engine/eval/README.md`。

## [v1.8.1] - 2026-07-01

### 新增

- **關於視窗顯示 git 版本碼**：「關於老王注音」現在顯示 `版本 (build · git 短碼)`，讓使用者與維護者能精確辨識目前執行的是哪一份原始碼，即使版本號未變也不會混淆。git 短碼由 build phase「Stamp Git Revision」在建置時寫入。

### 變更

- **L2 句末自動校正改走低調隱形提示**：修正建議改為掛在 `InputState.Inputting` 已預留的 `pendingAISuggestion` / `aiTooltipMessage` 欄位（顯示的單一真相來源），提示文字收斂為低調的「建議 …（Tab）」；採用（Tab）仍由 Coordinator 持有的真相來源決定，行為維持非破壞性、實驗開關預設不變。

### 文件

- 新增 `docs/engine-node-override.md`：引擎節點覆寫（真正「邊打邊隱形修正」）的風險評估與分階段設計；不動碼，先定地基與決策點（UOM 汙染、跨層邊界、使用者自主權為最尖銳風險）。
- 新增 `docs/l2-autocorrect-verification.md`：L2 句末自動校正 + 低調提示的實機驗證清單。
- 清除 `CHANGELOG.md` 與程式註解中對已棄用 `~/Documents/` 設計文件的殘留引用，改指向 `AI_HANDOFF_PROMPT.md` 與 `docs/`。

## [v1.8.0] - 2026-06-26

AI 隱形中文警察重構階段一：把 L1/L2 的狀態與決策集中到單一 Coordinator，並把 L2 句末自動校正改回非破壞性行為。架構重整為主，行為向後相容。

### 新增

- AI 隱形中文警察重構：新增 `AIAssistCoordinator.swift`，集中 L1/L2 的狀態、排程、serial 與 accept 決策，成為單一真相來源。
- 定義 `CandidateRescorer` / `SentenceCorrector` 協議，讓 L1 明確為快速 n-gram 層。
- 在 InputState 預留 `pendingAISuggestion`、`aiTooltipMessage` 等欄位，為低調隱形 UI 準備。
- 補上 `AIAssistCoordinator` 純決策的單元測試（accept 配對、consume bump serial、reset）。

### 變更

- L2 句末自動校正維持「只跳低調提示、按 Tab 才套用」的非破壞性行為；採用走既有 commit 出口。
- serial 過期判斷與 accept 配對由 Coordinator 擁有，Controller 只負責把結果套到 state；清理散落的 ai* 直接存取與死碼。
- 保留階段性開關（`enableAICandidateRerank` / `enableAIAutoCorrection`），預設不變。

### 修正

- 移除 L2 早期版本用 `setMarkedText` 直接覆蓋組字區的「假修正」：注音引擎為讀音驅動，該做法不更新引擎狀態，會被下一個按鍵或送出蓋回原文，且違反「只在引擎狀態裡操作」原則。

### 備註

- 這是「AI 隱形中文警察」設計報告階段一的重構基礎。L1 仍只重排候選、不生成；行為向後相容。
- 真正的「邊打邊隱形修正」需走引擎節點覆寫（僅適用讀音不變的同音/近音錯字），待 Coordinator 穩定後另行設計；改讀音的整句校正本質上只能在 commit 邊界套用。
- 詳細交班與後續提示見 `AI_HANDOFF_PROMPT.md` 交班日誌;引擎節點覆寫的風險評估見 `docs/engine-node-override.md`。

## [v1.7.5] - 2026-06-26

即時候選重排改為本機 n-gram scorer,並補齊 rescorer eval / training 工具。

### 變更

- **L1 候選重排不再呼叫本機 llama-server**:打字當下的候選建議改為進程內 character n-gram scorer,只在引擎已產生的合法候選裡重排,不生成新文字。
- **候選上下文更精準**:L1 rerank context 新增 composing buffer 的 cursor index,用目前候選所在位置替換評分,避免把候選誤接在 buffer 尾端。
- **避免無效重建候選窗**:若 scorer 選中的本來就是第一候選,直接清掉提示狀態,不重建相同候選列表。

### 新增

- `Source/Engine/eval/cases.tsv`:把 rescorer seed cases 從 C++ 程式碼抽成 TSV,方便追加 Johnny 的真實錯選測資。
- `Source/Engine/eval/train_char_ngram.py`:可從純文字或 `.bz2` 維基 dump 訓練 character unigram / bigram / trigram TSV 模型,支援 `--max-text-chars` 用部分語料快速實驗。
- `Source/Engine/eval/fetch_zhwiki_corpus.sh`:下載 / resume 中文維基 dump 到 ignored corpus 目錄。
- `Source/Engine/eval/README.md`:記錄 baseline、外部語料訓練、generated model 與 app fallback 行為。

### 備註

- 目前尚未把外部語料模型包進 app;app 若找不到 bundled `rescorer-char-ngrams.tsv`,會從既有 `data.txt` 建立小型 fallback model。
- 部分維基語料已證實可訓練與評測,但目前 10M / 50M 字實驗沒有改善 8 筆 seed case 的整體分數,因此不作為正式模型發佈。

## [v1.7.4] - 2026-06-26

語音輸入新增「辨識來源」三選一(實驗功能)。

### 新增

- **語音辨識來源可切換(輸入法選單)**,三選一:
  - **Apple(離線)**:系統內建辨識,離線、零成本(預設,即原行為)。
  - **Apple + AI 修正**:Apple 辨識後再過一次目前選的 AI 後端修正錯字與標點,離線。AI 修正失敗時自動退回原文,不卡語音。
  - **OpenAI Whisper(雲端)**:錄完整段上傳 OpenAI transcription API 辨識,辨識力最強;需使用者自備 OpenAI API key(按量付費、需連網),輸出統一過 OpenCC 轉繁。
- 「AI 修正設定…」新增 OpenAI 語音 API key(存 Keychain)與語音模型欄位(預設 `whisper-1`)。

### 備註

- OpenAI Whisper 來源為雲端可選後端,與 ChatGPT/Codex 訂閱不同,需另備 OpenAI Platform API key。
- 語音相關仍屬實驗功能;Whisper 錄音與上傳路徑尚待更廣泛實機驗證。

## [v1.7.3] - 2026-06-26

語音輸入收尾:辨識自動結束提示、使用說明文件、清理未使用字串。

### 新增

- **辨識器自行結束時補上提示**:當語音辨識偵測到句尾或達到時間上限而自行結束（非使用者主動雙擊停止）時,出字後會顯示「語音這段已自動結束,請再連按兩下右 Shift 重新開始」,避免麥克風被靜默關閉、使用者仍對著已結束的 session 繼續說話卻不自知。
- **README 新增「語音輸入(實驗)」使用說明區段**:含前置設定（開啟系統聽寫）、首次兩段式授權、操作步驟與常見狀況排查。

### 移除

- 清除未使用的「辨識中…(Recognizing…)」在地化字串（Base / en / zh-Hant 三語）。

## [v1.7.2] - 2026-06-25

語音輸入穩定性與首次授權流程修正。

### 修正

- **修正首次語音授權後輸入法可能跳回 ABC**:macOS 權限視窗會暫時改變前景程序與輸入源;現在只在授權前確實是老王注音時記住輸入源,授權完成後若目前仍停在 Apple 鍵盤 layout,會把輸入源恢復回老王注音。若使用者已切到其他第三方輸入法則不強制切回。
- **修正語音啟動時可能因 AVAudioEngine tap 格式崩潰**:新增 Objective-C 安全包裝攔截 `installTap` 例外,並依序嘗試 input/output/standard/nil audio format,避免 CoreAudio 格式不相容時讓 IME crash 後被 macOS fallback 到 ABC。
- **修正首次授權後立刻開始錄音的 UX**:第一次雙擊右 Shift 只處理語音辨識與麥克風授權;授權完成後顯示提示,使用者需再雙擊右 Shift 才開始錄音。
- **修正語音通知重疊**:停止錄音後若沒聽到內容或發生錯誤,只顯示對應提示;只有成功辨識並提交文字後才顯示「語音輸入已結束」。

### 變更

- 已授權狀態下,雙擊右 Shift 後以短緩衝啟動錄音,不再使用首次授權流程需要的長延遲。
- 移除本次診斷用的固定檔寫入 log,正式版不再寫入 `~/Library/Logs/laowang-voice-auth-diagnosis.log`。

## [v1.7.1] - 2026-06-25

語音輸入體驗微調:換熱鍵避開系統聽寫衝突,並補上辨識回饋。

### 變更

- **語音輸入熱鍵由「連按兩下 Control」改為「連按兩下右 Shift」**:macOS 內建聽寫常把「連按兩下 Control」綁為啟動快捷鍵,會與本功能搶麥克風。改用系統預設沒有綁定的右 Shift,**永久零衝突,使用者不必更動任何系統設定**。

### 新增

- **辨識回饋**:雙擊結束後到文字出現之間(on-device 收尾辨識有零點幾到數秒空窗),顯示「辨識中…」避免像沒反應;若沒聽到任何內容,顯示「沒聽到內容」。

## [v1.7] - 2026-06-25

新增 Phase 3「語音輸入」:對著麥克風講話,直接把字送進輸入欄。離線、用 Apple 內建語音辨識,零內嵌模型。

### 新增

- **L3 語音輸入(Phase 3,實驗功能)**:用 Apple 內建 `SFSpeechRecognizer`(繁體中文 zh-TW,優先 on-device 離線辨識)把語音轉成文字,辨識結果走既有 commit 出口落地,不繞 `KeyHandler` / `InputState`、不碰打字流程。零內嵌模型、可離線使用。
- **連按兩下 Control 的 push-to-talk**:連按兩下 Control 開始聆聽、再連按兩下 Control 結束並出字,全程不必離開鍵盤去點選單。為避免和 Ctrl+C 等快捷鍵混淆,只認「兩次乾淨的 Control 單擊」(兩擊之間不夾其他按鍵、不同時按其他修飾鍵)。輸入法選單的「語音輸入(實驗)」項仍可作為備援觸發。
- **聽寫未開啟時的引導提示**:on-device 離線辨識需要系統「聽寫」開啟;未開啟時會提示前往「系統設定 ▸ 鍵盤 ▸ 聽寫」開啟,而非只報失敗。

### 備註

- 已實機驗證:macOS 輸入法(input method)程序確實能取得麥克風授權並穩定錄音、辨識、出字(這是 Phase 3 最大的技術風險,現已排除)。
- 首次使用需在「系統設定 ▸ 鍵盤 ▸ 聽寫」開啟聽寫並允許麥克風 / 語音辨識授權;第一次開啟聽寫會下載離線語音模型(需一次性網路),之後可離線使用。

## [v1.6] - 2026-06-25

新增 Phase 2「句末自動校正」實驗功能,並強化 AI 對在/再、的/得/地的判別。

### 新增

- **L2 句末自動校正(Phase 2 MVP,實驗功能,預設關閉)**:開啟後,打到句末標點(。！？!?…)時自動在背景用本機模型校正整句。第一版刻意保守:**只跳建議提示、不自動改字**,使用者按 Tab 才採用;手動 ⌘Return 的「直接套用」行為維持不變。觸發比 L1 更克制(句末標點 + 長度達門檻 + 游標在句尾才觸發,逗號頓號不觸發),且非阻塞、過期結果丟棄。可在輸入法選單「AI 句末自動校正(實驗)」開關。

### 變更

- **AI 校正提示詞強化「在/再、的/得/地」判別**:L2 整句校正與 L1 候選重排的本機模型提示詞補上這兩組同音虛字的判別規則與對比例句。實測本機模型在「再/在」與平翹舌、鄰鍵錯字命中率提升且無退步;「得/地」這類仍受小模型能力限制,待後續領域微調處理。

## [v1.5.4] - 2026-06-24

品質修復版:修好開發測試流程,並讓 L1 候選建議更克制。

### 修正

- **完整 `xcodebuild test` 不再卡死**：以往整包測試會永久停住,根因有二且皆已修正。
  - 測試以 app 當 test host 啟動時不再 spawn 內嵌 llama-server、不再連網檢查更新(以 `XCTestConfigurationFilePath` 偵測測試環境)。
  - `VersionUpdateApiTests` 在未設定更新端點時不再因 continuation 永不 resume 而卡死。
  - 現況:110 個測試 / 9 個 suite 約 4 秒全綠並乾淨結束。

### 變更

- **L1 AI 候選建議觸發條件收緊**:`hasPhraseAlternativeCollision` 由「候選裡有任兩個不同的多字詞就觸發」改為「多字候選彼此近似同音(音節數相同、僅差一個音節)才觸發」,降低過度觸發、減少不必要的本機推理。

## [v1.5.3] - 2026-06-24

### 新增

- **終端機一鍵安裝** `scripts/install.sh`：不需打開 `.app`，完全避開 Gatekeeper。
- DMG 內附 `若 Gatekeeper 擋住請看這裡.txt` 說明。

## [v1.5.2] - 2026-06-24

修正安裝流程過於混亂的問題。

### 變更

- DMG 內**只保留一個**「安裝老王注音.app」，移除其他檔案。
- 安裝完成後自動開啟「系統設定 → 鍵盤 → 輸入法」，並顯示逐步加入輸入法的說明。

### 移除

- DMG 內多餘的「老王注音.app」「拖曳到這個資料夾.app」「安裝說明.txt」（造成使用者不知道該點哪個）。

## [v1.5.1] - 2026-06-24

安裝體驗大幅簡化。

### 新增

- DMG 改為圖形化 **「安裝老王注音」** 安裝精靈（取代 `安裝.command`）。
- **「拖曳到這個資料夾」** 捷徑：一鍵開啟輸入法安裝位置，支援拖曳安裝。
- 輸入法啟動時自動清除 macOS quarantine（拖曳安裝後本機 AI 可自動就緒）。

### 變更

- 安裝精靈安裝完成後自動清除 quarantine。
- README 與 DMG 內說明改寫為標準 Mac 安裝流程。

### 移除

- DMG 內的 `安裝.command`（易遭 Gatekeeper 阻擋且不像一般軟體）。

## [v1.5] - 2026-06-24

L1 候選語意重排（Phase 1）首次發佈。

### 新增

- **L1 AI 候選建議**：候選字容易混淆時，依前後文重排候選順序；可按 Tab 採用建議。
- 150ms debounce、本機 server 暖機後自動重試（最多 6 次）。
- 觸發條件：候選同音（相同注音、不同字）+ 歧義字 + 多候選差異判斷。
- 輸入法選單與偏好設定「進階」分頁可切換「AI 候選建議」。

### 變更

- `AICandidateRerankContext` 改為帶入候選注音；rerank prompt 會附上 `(注音)` 輔助判斷。
- L1 測試補強：水果店、資道、同音候選等 golden case。

## [v1.4] - 2026-06-24

### 變更

- 品牌名由 bopomofo 改為 zhuyin,與中文「老王注音」對齊:
  - GitHub repo 由 `laowang-bopomofo` 更名為 `laowang-zhuyin`(舊網址自動轉址)。
  - 英文產品名 `LaoWang Bopomofo` 改為 `LaoWang Zhuyin`(About、偏好設定、選單、安裝器等顯示文字)。
  - 發佈 DMG 檔名由 `LaoWangBopomofo.dmg` 改為 `LaoWangZhuyin.dmg`。
- 不更動:功能字「Bopomofo / 注音」、上游 `McBopomofo` 內部識別(target/bundle id/input source id/module/namespace/資料路徑)。

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

[v1.9.1]: https://github.com/TsungLi-Wang/laowang-zhuyin/releases/tag/v1.9.1
[v1.9.0]: https://github.com/TsungLi-Wang/laowang-zhuyin/releases/tag/v1.9.0
[v1.8.1]: https://github.com/TsungLi-Wang/laowang-zhuyin/releases/tag/v1.8.1
[v1.8.0]: https://github.com/TsungLi-Wang/laowang-zhuyin/releases/tag/v1.8.0
[v1.5.3]: https://github.com/TsungLi-Wang/laowang-zhuyin/releases/tag/v1.5.3
[v1.5.2]: https://github.com/TsungLi-Wang/laowang-zhuyin/releases/tag/v1.5.2
[v1.5.1]: https://github.com/TsungLi-Wang/laowang-zhuyin/releases/tag/v1.5.1
[v1.5]: https://github.com/TsungLi-Wang/laowang-zhuyin/releases/tag/v1.5
[v1.4]: https://github.com/TsungLi-Wang/laowang-zhuyin/releases/tag/v1.4
[v1.3]: https://github.com/TsungLi-Wang/laowang-zhuyin/releases/tag/v1.3
[v1.2]: https://github.com/TsungLi-Wang/laowang-zhuyin/releases/tag/v1.2
[v1.1]: https://github.com/TsungLi-Wang/laowang-zhuyin/releases/tag/v1.1
[v1.0]: https://github.com/TsungLi-Wang/laowang-zhuyin/releases/tag/v1.0
