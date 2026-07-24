# 老王注音 — 選單功能全對照盤點（feature inventory）

> **性質**：只讀稽核 + 文件。不改行為、不動 flag、不發版。  
> **產物棒次**：2026-07-24。  
> **實機版本**：v2.6.0 build 2290（`~/Library/Input Methods/McBopomofo.app`）。  
> **偏好域**：`org.openvanilla.inputmethod.McBopomofo`（`defaults read` 實讀）。  
> **總交接檔對照**：`~/Documents/老王注音-專案總交接檔-v2.6.0出貨後全貌.md`（L0/L0+/L0++/L1/L2/L3 分層）。

---

## ⚠️ 置頂：外部網路／雲端依賴（哲學紅線）

設計哲學寫的是「**進程內、無外部依賴**」。下列為**現存**對外路徑，盤點時必須 Johnny 知悉：

| 路徑 | 何時觸發 | 傳什麼 | 嚴重度 | 證據 |
|---|---|---|---|---|
| **Claude Opus 整句修正** | 選單選「Claude Opus(雲端・最準)」且按 ⌘Return | 組字區全文 + 游標前文 ≤100 字 → `https://api.anthropic.com/v1/messages` | **紅（主動雲端校正）** | `ClaudeAICorrector.swift`；預設 endpoint / model 在 `AICorrection.swift` |
| **llama 模型首次下載** | 本機 AI 首次使用且 Application Support 無模型 | 從 HuggingFace 下載 2.89GB GGUF（一次性） | 黃（一次性資產下載） | `LlamaServerManager.modelDownloadURLString` |
| **whisper 模型首次下載** | 語音輸入首次使用且無模型 | HuggingFace `ggml-large-v3-turbo-q5_0.bin` ~574MB | 黃 | `WhisperServerManager.swift` L74 |
| **檢查更新** | 啟動自動 / 選單手動 | 讀更新 plist（GitHub releases 站） | 低 | `AppDelegate` `VersionUpdateApi`；`UpdateInfoSite` |

**Johnny 實機現值**：`AICorrectionBackend = 3`（本機 AI），**未選 Claude**。  
因此日常打字的常駐 `llama-server` 是本機 127.0.0.1，**不是**雲端。  
但選單仍提供 Claude 切換入口；一旦切過去並按 ⌘Return，組字文字會出網。

---

## 0. 總表（選單可見項）

選單定義入口：`Source/InputMethodController.swift` `menu()`（約 L85–245）。

| # | 選單文案（zh） | 偏好鍵 | 程式預設 | Johnny 實機 | 模型 | 改 commit 結果？ | 分層 | 來源 |
|---|---|---|---|---|---|---|---|---|
| 1 | 輸出簡體中文 (^⌘G) | `ChineseConversionEnabled` | OFF | **OFF** | 無（OpenCC 規則） | 是（送出時轉簡） | 分層外（輸出後處理） | 上游 McBopomofo |
| 2 | 使用半形標點符號 (^⌘H) | `HalfWidthPunctuationEnable` | OFF | **OFF** | 無 | 是（標點字元不同） | 分層外 | 上游 |
| 3 | 聯想詞 | `AssociatedPhrasesEnabled` | OFF | **OFF** | 無（聯想表） | 否（選後才進 buffer） | 分層外 | 上游 AssociatedPhrasesV2 |
| 4 | AI 候選建議 | `EnableAICandidateRerank` | **ON** | **ON** | n-gram（預設路徑）；見 §4 | 間接（改候選序→人若照選才改字） | **L1** | fork |
| 5 | AI 句末自動校正（實驗） | `EnableAIAutoCorrection` | OFF | **ON** | 本機 llama（Qwen3-4B） | 否（只提示；Tab 才 commit 建議） | **L2 自動** | fork |
| 6 | 同音字智慧消歧（實驗） | `EnableConfusionPairDisambiguation` | OFF | **ON** | 規則表 log-odds | 是（walk 後 soft 改選） | **L0 附掛** | fork |
| 7 | AI 神經候選重排（實驗） | `EnableGlobalNeuralRerank` | OFF | **ON** | 本機 llama 整句 logprob | 是（候選序 / 延遲隱形改選） | **L1 神經 + L1.5** | fork |
| 8 | 情境化選字 | `EnableContextualWalk` | **ON** | **ON** | 詞 bigram TSV（λ=0.75） | 是（逐鍵 walk 路徑） | **L0** | fork v2.2→v2.3 |
| 9 | 神經路徑重排（實驗） | `EnableNeuralPathRerank` | **ON** | **ON** | 進程內 v2c int8 LSTM | 是（**僅 Enter commit**） | **L0+** | fork v2.6.0 |
| 10 | 語音輸入 | （無持久 toggle；動作項） | — | 可觸發 | whisper.cpp 本機 | 是（直接 insert 辨識字） | **L3** | fork |
| 11 | AI 修正模型：Claude / 本機 | `AICorrectionBackend`（2/3） | 3 本機 | **3** | Claude 雲 / llama 本機 | 影響 ⌘Return 結果 | **L2 手動** | fork |
| 12 | AI 修正設定… | Keychain + UserDefaults | — | — | — | 設定 API key | L2 設定 | fork |

偏好實讀指令與結果（2026-07-24）：

```text
$ defaults read org.openvanilla.inputmethod.McBopomofo
ChineseConversionEnabled = 0
HalfWidthPunctuationEnable = 0
AssociatedPhrasesEnabled = 0
EnableAICandidateRerank = 1
EnableAIAutoCorrection = 1
EnableConfusionPairDisambiguation = 1
EnableGlobalNeuralRerank = 1
EnableContextualWalk = 1
EnableNeuralPathRerank = 1
AICorrectionBackend = 3
```

與 Johnny 截圖勾選狀態**一致**。

---

## 1. 各功能詳節

### 1.1 輸出簡體中文（^⌘G）

1. **白話**：開著時，送出到 App 的漢字會轉成簡體；組字預覽仍可能是繁體（視轉換 style）。  
2. **入口**：`Preferences.chineseConversionEnabled` / `toggleChineseConverter`；送出時 `InputMethodController.commit(text:)` → `OpenCCBridge.convertToSimplified`。鍵：`ChineseConversionEnabled`。  
3. **觸發**：commit 出口（任何 `InputState.Committing` / force-commit 最終 insert）。  
4. **模型**：不用；OpenCC 規則。  
5. **commit 影響**：有。  
6. **與神經路徑重排**：無關；重排在引擎側繁體路徑上做完，之後才可能轉簡。  
7. **預設 OFF / 實機 OFF**。  
8. **分層**：分層外輸出後處理。  
9. **來源**：上游 McBopomofo。

### 1.2 使用半形標點符號（^⌘H）

1. **白話**：開著時，標點鍵對應半形（`,.` 等）；關著用全形／注音標點表。  
2. **入口**：`Preferences.halfWidthPunctuationEnabled`；`KeyHandler.mm` 選 prefix `_half_punctuation_` vs `_punctuation_`（約 L1003–1006）。鍵：`HalfWidthPunctuationEnable`。  
3. **觸發**：按標點鍵時選字典 reading。  
4. **模型**：不用。  
5. **commit 影響**：標點字元不同會改送出字。  
6. **與神經路徑**：標點進組字區（見 T2），**不**觸發 L0+ rerank。  
7. **預設 OFF / 實機 OFF**。  
8. **分層外**。  
9. **上游**。

### 1.3 聯想詞

1. **白話**：選字或打完一節後，可能跳出下一詞聯想窗；選了才加字。  
2. **入口**：`Preferences.associatedPhrasesEnabled`；`KeyHandler` `handleAssociatedPhraseWithState` + `AssociatedPhrasesV2`；資料 `associated-phrases-v2.txt`。鍵：`AssociatedPhrasesEnabled`。  
3. **觸發**：候選選定後 / 注音完成後 auto-trigger（Bopomofo 模式）；Shift+Enter 可手動開聯想。  
4. **模型**：不用（聯想表）。  
5. **commit 影響**：Bopomofo 模式聯想選完仍多半回 `Inputting`（未直接 commit）；Plain 模式會 commit。  
6. **與神經路徑**：聯想路徑**不**設 `_rerankThisWalk`。  
7. **預設 OFF / 實機 OFF**。  
8. **分層外 UX**。  
9. **上游**（AssociatedPhrasesV2）。

### 1.4 AI 候選建議（L1 閘門）

1. **白話**：打開候選窗時，若偵測到同音／近似同音衝突，背景重排候選順序，或顯示「AI 建議：…（Tab）」；**Tab** 可直接送出建議句。  
2. **入口**：  
   - Flag：`EnableAICandidateRerank`（`Preferences.enableAICandidateRerank`，預設 true）  
   - 排程：`scheduleAICandidateRerankIfNeeded`（候選窗 state）→ `AIAssistCoordinator.scheduleRerank`  
   - 實際 scorer 預設為 `NeuralCandidateRescorer`（見 1.7）  
3. **觸發**：進入 `InputState.ChoosingCandidate` 後 debounce 0.15s；需 buffer ≥2 且碰撞條件成立。  
4. **模型**：  
   - `EnableGlobalNeuralRerank=OFF` 時：字元 n-gram（`AICandidateNGramScorer`）。  
   - 程式找 `rescorer-char-ngrams.tsv`；**出貨 bundle 無此檔**，fallback `data.txt`（證據：`AICandidateReranker.swift` L205、L322–337；bundle 列表僅有 `path-char-ngrams.tsv` / `data.txt`）。  
   - `EnableGlobalNeuralRerank=ON` 且右文 ≥2 字且 server ready：llama 整句 logprob（`AISentenceScorer`）。  
5. **commit 影響**：重排本身只改候選窗順序；**Tab 採用**或使用者選新 top 才改字。  
6. **與神經路徑重排（L0+）**：不同層。L1 在**候選窗**；L0+ 在 **Enter commit**。不互相覆寫同一變數，但可能先後改「你看到的字」。  
7. **預設 ON / 實機 ON**。  
8. **L1**。  
9. **fork**（`9b86c4b` 等）。

### 1.5 AI 句末自動校正（實驗）

1. **白話**：打到夠長、游標在句尾、且有句末標點（。！？…）或長句含歧義字時，背景用本機 LLM 想一個修正句，**低調提示**「建議：…（Tab）」；**不會自動改組字**。Tab 才送出建議。  
2. **入口**：`EnableAIAutoCorrection`；`AIAutoCorrector.shouldSchedule`；`scheduleAIAutoCorrectionIfNeeded` on `Inputting`；`LocalServerSentenceCorrector` → `LocalServerAICorrector` → llama `/v1/chat/completions`。  
3. **觸發**：組字區更新後 debounce **0.8s**；min 長度 4；句末標點或（長度≥8 且含歧義字）。  
4. **模型**：**本機 llama**（與 ⌘Return 本機後端同一 server）。**不走 Claude**（自動校正硬綁 `LocalServerSentenceCorrector`）。需模型已安裝。  
5. **commit 影響**：預設否（hint only）。Tab → `commitAIAutoCorrection` 直接 `Committing` 建議字串（**繞過**神經路徑重排）。  
6. **與 L0+**：Tab 採用路徑**不**跑 `NeuralLMPathScorer`。  
7. **預設 OFF / 實機 ON**（使用者手動開）。  
8. **L2 自動**（總交接 L2 主要指 ⌘Return；自動校正是 L2 的旁支）。  
9. **fork**（`535316e`）。

### 1.6 同音字智慧消歧（實驗）

1. **白話**：組字 walk 完後，對特定同音對（目前表頭為 **ㄗㄞˋ → 在/再**）用鄰字 log-odds 軟改選；不重切詞。  
2. **入口**：`EnableConfusionPairDisambiguation`；`KeyHandler._walk` 末尾 `_confusionPairDisambiguator->rescoreWalk`；表 `confusion-pairs.tsv`。  
3. **觸發**：**每次** `_walk`（含逐鍵），非 commit-only。  
4. **模型**：規則／計數表（語料 log-odds），非神經。  
5. **commit 影響**：是（組字預覽與最終字都可能變）。  
6. **與 L0+**：先 confusion soft override 在 walk 結果上；Enter 時 L0+ n-best rerank 在**另一次** commit walk（帶 path scorer）。順序：逐鍵 walk(+confusion) → Enter 再 walk(+LSTM rerank + confusion)。使用者硬 override 不被 confusion 動。  
7. **預設 OFF / 實機 ON**。  
8. **L0 附掛**（總交接檔較少獨立成章，屬盲區之一）。  
9. **fork**（`45fc66b`）。

### 1.7 AI 神經候選重排（實驗）≡ Global Neural Rerank

1. **白話**：兩段：  
   - **候選窗 L1 神經**：右文夠時用本機 4B 模型比候選整句機率，margin>1 才翻序。  
   - **L1.5 延遲全局重審**：組字繼續打、右文出現後，對「的/得/地…」等字集 debounce 0.6s 隱形 soft 改選（不碰 在/再——留給混淆表）。  
2. **入口**：`EnableGlobalNeuralRerank`；`NeuralCandidateRescorer`；`scheduleNeuralDeferredCheckIfNeeded`；啟動時 `startLocalServerIfNeeded` 若此 flag ON 會暖 llama。  
3. **觸發**：候選窗 / Inputting 更新；非逐鍵同步阻塞。  
4. **模型**：本機 **Qwen3-4B-Instruct-2507 Q5_K_M** via llama-server（見 T3）。  
5. **commit 影響**：是（隱形改選改 composing；候選序影響人工選擇）。  
6. **與 L0+ 神經路徑重排**：  
   - **不同模型**（4B LLM vs 進程內 char-LSTM）。  
   - **不同時機**（組字中 / 候選窗 vs Enter）。  
   - 不共用 scorer 物件；可能**先後**改同一句，Enter 時 L0+ 以當下 lattice 再 n-best 重排一次。  
7. **預設 OFF / 實機 ON** → 這是實機常駐 ~3GB llama 的主因之一。  
8. **L1 神經 + L1.5**（總交接 L1 寫「候選視窗排序」；L1.5 延遲重審屬交接檔弱覆蓋區）。  
9. **fork**（`da91fbf`、`9871e64` 等）。

### 1.8 情境化選字

1. **白話**：打每個音節完成 walk 時，用「前詞→本詞」bigram PMI 調整路徑分數，讓「這句話在台灣語料裡較常見」的切法勝出。  
2. **入口**：`EnableContextualWalk`；`KeyHandler._walk` → `CorpusBigramContextModel` + `CompositeContextModel`（可疊 UOM soft）；資源 `word-bigrams.tsv`（~24MB）。λ=0.75 寫死於 load。  
3. **觸發**：**逐鍵** walk（0.1ms 級）。  
4. **模型**：計數 bigram（非神經）。UOM 個人化 soft 與本開關獨立（有 cache 就掛）。  
5. **commit 影響**：是（組字預覽即已改變）。  
6. **與 L0+**：L0+ 在 walk 分數之上再加 ν·LSTM；公式 `final = walk + ν·LSTM`。情境化是 walk 分的一部分。  
7. **預設 ON / 實機 ON**。  
8. **L0**。  
9. **fork** v2.2.0→v2.3.0。

### 1.9 神經路徑重排（實驗）— 出貨 L0+

1. **白話**：按 **Enter 送出** 時，對整句做 n-best(10) + char-LSTM 重排，可能把組字預覽的錯字在送出瞬間改對（「跳字」）。逐鍵預覽**刻意**不跑。  
2. **入口**：`EnableNeuralPathRerank`（預設 true）、`NeuralPathRerankNu`（0.75）；`KeyHandler._handleEnterWithState` 設 `_rerankThisWalk=YES` 再 `_walk`；`NeuralLMPathScorer` 載入 bundle `path-char-lstm.bin`。  
3. **觸發**：**僅** `_handleEnterWithState`（Bopomofo 模式）。Plain Bopomofo 排除。  
4. **模型**：進程內 **v2c int8** char-LSTM  
   - 檔：`Source/Data/path-char-lstm.bin` / app `Contents/Resources/path-char-lstm.bin`  
   - 格式：`LWLSTM8`；**emb=256 hidden=512 layers=2 vocab=7875**（與 eval v2c 架構一致）  
   - 大小：9.5MB；SHA256：`ebd603195275622570c79127f61e0d37efe56fe17c61048bc0af9f01b59866ba`  
   - 注意：同目錄 `path-char-lstm.meta.txt` 仍寫 emb=64/1.1M params，**與二進位不符（過期 meta）**；eval 全精度 v2c SHA `f04bca59…` 為 37MB fp 檔，出貨為 int8 量化版。  
5. **commit 影響**：**是**（Enter 路徑）。  
6. **與其他 AI 功能**：見各節；L0+ 不呼叫 llama。  
7. **預設 ON / 實機 ON**（交接檔記載過偏好殘留 OFF bug；本次實讀已 ON）。  
8. **L0+**（出貨主角）。  
9. **fork** v2.6.0 `51c930c`。

### 1.10 語音輸入

1. **白話**：連按兩下右 Shift 開始/停止錄音；辨識完直接上字。選單項也可 Toggle。  
2. **入口**：`WhisperVoiceInputManager` / `WhisperServerManager`；`toggleVoiceInput`；`commitVoiceRecognizedText`。  
3. **觸發**：雙擊右 Shift 或選單；**非**逐鍵。  
4. **模型**：本機 whisper-server，`ggml-large-v3-turbo-q5_0` ~547MB @ Application Support；實機 RSS ~603MB。  
5. **commit 影響**：是（直接 insert）。**不**經 lattice / L0+。  
6. **與 L0+**：無。  
7. **無開關預設**；模型已裝。  
8. **L3**。  
9. **fork**（`5e90197` 等）。

### 1.11 AI 修正模型切換 + ⌘Return（L2 手動）

見 **T4**。後端 2=Claude 雲端、3=本機 llama。

---

## T2. Commit 路徑清單 × 是否觸發神經路徑重排（L0+）

**裁決原則**：L0+ 只在 `KeyHandler._handleEnterWithState` 內把 `_rerankThisWalk=YES` 後 `_walk`（`KeyHandler.mm` L1455–1473、L2783–2813）。其他 `InputStateCommitting` **都不**設此旗標。

| # | 路徑 | 證據位置 | 觸發 L0+？ | 備註 |
|---|---|---|---|---|
| 1 | **Enter**（組字中、非 Ctrl/Shift 特化） | `_handleEnterWithState` | **是** | 出貨唯一接線路徑 |
| 2 | **Shift+Enter** | L940–942 聯想，不進 `_handleEnterWithState` | 否 | 開聯想窗 |
| 3 | **Ctrl+Enter** | L908–938 特殊輸出（注音/HTML…） | 否 | 且內容常非組字原文 |
| 4 | **空白鍵** 在句尾且「空白選字」關 或 按住 Shift | L822–835 commit buffer + `" "` | **否** | 交接待辦「補接」成立 |
| 5 | **空白鍵** 開候選窗後選字 | 選字→Bopomofo 回 Inputting | 否（未 commit） | Bopomofo 模式選字不送出 |
| 6 | **數字鍵選候選** | `didSelectCandidate` Bopomofo → Inputting | 否 | 同上 |
| 7 | **標點鍵** | `_handlePunctuation` `insertReading` + walk → **仍 Inputting** | **否** | **證實 Johnny 實測：標點進組字區，不 commit** |
| 8 | **失焦 / commitComposition** | `handleForceCommitWithStateCallback` L525–538 | **否** | 直接偷 composingBuffer |
| 9 | **handle(nil event)** | `commitComposition` | 否 | 同上 force-commit |
| 10 | **切換輸入法 / Deactivated** | `handle Deactivated` commit previous buffer | 否 | |
| 11 | **Ctrl+\` Big5** 進入前 | L949–955 commit composing | 否 | |
| 12 | **Ctrl+\\ 功能選單** 進入前 | L963–969 | 否 | |
| 13 | **Plain Bopomofo** 唯一候選自動送 | L782–787 等 | 否 | 且 L0+ 在 plain 模式整段關閉 |
| 14 | **⌘Return AI 校正** | `applyAICorrectionResult` 直接 Committing | 否 | 自由文本，非 lattice |
| 15 | **Tab 採用 AI 建議** | `commitAISuggestion` / `commitAIAutoCorrection` | 否 | 同上 |
| 16 | **語音辨識完成** | `commitVoiceRecognizedText` | 否 | |
| 17 | **數字模式 / 伊呂波 / 日期巨集選字** | CandidateControllerDelegate | 否 | |

### 懸案裁決：「補接 commit 路徑」待辦是否成立？

**成立。**

證據鏈：

1. L0+ 閘門註解自承「COMMIT-TIME ONLY」且只在 Enter 路徑打開（`KeyHandler.mm` L1461–1464、L2783–2787；`v2.6.0-shipping-wiring.md` Follow-ups）。  
2. 標點：`_handlePunctuation` 在 Bopomofo 只 `insertReading` + `buildInputtingState`，**不** `InputStateCommitting`（L1513–1523）。Johnny「標點進組字區不觸發 commit」**與 code 一致，不能推翻**。  
3. 空白鍵句尾 commit（L822–835）**不**呼叫 `_handleEnterWithState`，故 **不** rerank。  
4. 失焦 force-commit 同樣不 rerank。

因此：若使用者習慣「打完用標點／空白結束」而非 Enter，**會吃不到 387 那套 L0+ 增益**。待辦「其他 commit 觸發補接 rerank」有 code 依據，不是臆測。

---

## T3. llama-server 身分調查

### 進程證據（2026-07-24 本機）

```text
PID  1493  RSS ≈ 3012 MB
/Users/.../McBopomofo.app/Contents/Resources/llama/bin/llama-server
  -m ".../Application Support/McBopomofo/AIModel/model.gguf"
  --host 127.0.0.1 --port 49588 -c 2048 -ngl 99 --no-webui

PID  2007  RSS ≈ 603 MB   (whisper-server，語音；非 llama)
PID  1489  RSS ≈ 76 MB    (IME 主進程)
```

### 誰啟動

| 條件 | 行為 | 證據 |
|---|---|---|
| App 啟動且（`AICorrectionBackend==3` **或** `EnableGlobalNeuralRerank`） | `startLocalServerIfNeeded` 背景 spawn | `AppDelegate.applicationDidFinishLaunching` L200；`+AICorrection` L66–73 |
| 使用者勾「AI 神經候選重排」 | start / 必要時下載 | `toggleGlobalNeuralRerankEnabled` L452–462 |
| 切到本機 AI 後端 | start | `setAIBackend` L645–658 |
| 首次無模型 | HuggingFace 下載後再 start | `ensureModelDownloaded` |

Johnny 實機兩者皆 ON（後端 3 + GlobalNeural ON）→ **開機即常駐**。

### 載什麼模型

| 項 | 值 | 證據 |
|---|---|---|
| 路徑 | `~/Library/Application Support/McBopomofo/AIModel/model.gguf` | ps argv + `LlamaServerManager.modelFileURL` |
| 身分 | **Qwen3-4B-Instruct-2507**，量化 **Q5_K_M** | GGUF metadata `general.name`；README `llama-runtime/README.md` |
| 大小 | 2,889,513,696 bytes（~2.69 GiB / 文件稱 ~2.9GB） | `modelExpectedSize`；`ls -lh` |
| SHA256 | `66713ce35a58a82fe87642d4ec13425bf9b9a46800fff5c49a665ef5701439dc` | 實算 == `modelExpectedSHA256` |
| 下載 URL | bartowski HF `Qwen_Qwen3-4B-Instruct-2507-Q5_K_M.gguf` | `LlamaServerManager` L76–77 |
| 監聽 | **僅 127.0.0.1**，隨機 port | argv `--host 127.0.0.1` |
| GPU | `-ngl 99` 全層 Metal | argv |

### 哪些功能呼叫它

| 功能 | 用法 |
|---|---|
| ⌘Return 本機 L2 | chat completions 生成校正句 |
| AI 句末自動校正 | 同上 chat |
| AI 神經候選重排 L1 | `AISentenceScorer` 鏈式 logprob 探針（非 chat） |
| L1.5 延遲重審 | 同上 scorer |

**不呼叫 llama**：情境化選字、同音消歧表、神經路徑重排（進程內 LSTM）、聯想、簡繁、半形。

### 關掉後會不會退出

| 動作 | llama 是否 stop |
|---|---|
| 取消「AI 神經候選重排」，且後端**不是**本機(3) | **會** stop（L460–462） |
| 取消「AI 神經候選重排」，後端仍是本機(3) | **不會**（⌘Return 還要） |
| 切到 Claude，且 GlobalNeural OFF | **會** stop（L656–658） |
| 只關「AI 句末自動校正」 | **不會**（不擁有 server 生命週期） |
| App 結束 | **會**（`applicationWillTerminate`） |

實機要放掉 ~3GB：需 **同時** 關閉 GlobalNeural **且** 後端改非本機（或殺進程／退出 IME）。

---

## T4. ⌘Return 偵察（L2 手動整句校正）

**一段話結論：**

⌘Return（`InputMethodController.handle` L325–331）在組字非空時呼叫 `triggerAICorrection`。後端由 `AICorrectionBackend` 決定：  
- **3（實機）**：`LocalServerAICorrector` → 本機 llama-server **chat**（system prompt `AICorrectionPrompt.localSystemPrompt`，temperature 0，max_tokens 64）→ 成功則 **直接 commit 校正句**（清空 lattice）。  
- **2**：`ClaudeAICorrector` → Anthropic Messages API（預設 `claude-opus-4-8`，需 Keychain API key）→ 同樣直接 commit。  

與「**AI 句末自動校正**」的關係：  
- **同一顆本機模型 / 同一 llama-server**（自動校正也走 `LocalServerAICorrector`）。  
- **不同觸發與 UX**：⌘Return = 手動、立刻套用；自動校正 = 句末條件 + 0.8s debounce + **只提示 Tab 採用**。  
- **不同於** L0+ 神經路徑重排（那是 v2c LSTM n-best，不自由生成）。  
- **不同於** L1 神經候選（logprob 排序，不生成新字串）。  

「重砲鍵」若要綁更強模型：現成分叉已在 `correctAIGuess` switch；本棒只查不改。

---

## 5. 執行順序總圖（Johnny 實機：幾乎全開）

```text
逐鍵注音完成
  → L0 walk（unigram + 情境 bigram λ=0.75 + UOM soft）
  → 同音消歧 soft（在/再表）
  → 組字預覽更新
  →（可）L1.5 延遲神經重審 debounce 0.6s（llama logprob）
  →（可）L2 自動校正 debounce 0.8s（llama chat，只提示）

打開候選窗
  → L1：n-gram 或（GlobalNeural+右文）llama logprob 重排候選

Enter
  → L0+ walkNBest(10)+v2c LSTM ν=0.75 → 可能改句 → commit
  →（可）簡繁轉換

標點 / 句尾空白 / 失焦
  → commit 或不 commit（見 T2）；**皆無 L0+**

⌘Return
  → llama/Claude 生成整句 → 直接 commit（無 L0+）
```

---

## 6. 交接檔盲區摘要（本棒補齊的）

總交接檔對 **L0 / L0+ / 研究 L0++ / L3 語音** 記載完整；下列在選單上存在但交接敘事薄弱或易混：

1. **AI 候選建議 vs AI 神經候選重排** 兩開關疊加（L1 n-gram 閘門 + llama 升級）。  
2. **AI 句末自動校正**（hint-only L2）與 **⌘Return**（force L2）差異。  
3. **同音字智慧消歧**（在/再表，逐鍵 soft）。  
4. **llama-server 常駐身分**（Qwen3-4B，~3GB；由本機後端 ∨ GlobalNeural 持有）。  
5. **Claude 雲端入口仍在選單**（哲學紅線）。  
6. **L0+ 只接 Enter**；標點不 commit（已 code 證實）。  
7. **出貨 `path-char-lstm.meta.txt` 過期**（二進位已是 v2c int8）。  
8. **L1 n-gram 資源名** `rescorer-char-ngrams.tsv` 未進 bundle，fallback `data.txt`。

---

## 7. 證據索引（路徑速查）

| 主題 | 檔案 |
|---|---|
| 選單 | `Source/InputMethodController.swift` `menu()` |
| 偏好鍵 | `Source/Preferences.swift` |
| Enter + L0+ 閘門 | `Source/KeyHandler.mm` `_handleEnterWithState`, `_walk` |
| 標點不 commit | `Source/KeyHandler.mm` `_handlePunctuation` |
| Force commit | `Source/KeyHandler.mm` `handleForceCommitWithStateCallback` |
| 候選選字 | `Source/InputMethodController+CandidateControllerDelegate.swift` |
| L1 / L2 協調 | `Source/AIAssistCoordinator.swift` |
| L1 神經 | `Source/AINeuralCandidateRescorer.swift`, `AISentenceScorer.swift` |
| L1.5 | `Source/InputMethodController+NeuralDeferred.swift` |
| L2 手動 | `Source/InputMethodController+AICorrection.swift` |
| L2 自動 | `Source/InputMethodController+AIAutoCorrection.swift`, `AIAutoCorrector.swift` |
| llama | `Source/LlamaServerManager.swift`, `LocalServerAICorrector.swift` |
| Claude | `Source/ClaudeAICorrector.swift` |
| 語音 | `Source/WhisperServerManager.swift` |
| 出貨 wiring | `Source/Engine/eval/analysis/v2.6.0-shipping-wiring.md` |
| 總交接 | `~/Documents/老王注音-專案總交接檔-v2.6.0出貨後全貌.md` |

---

## 8. 本棒未改動聲明

- 未改任何 preference 預設值、未動 flag、未改 KeyHandler / 引擎行為。  
- 未殺進程、未重裝 app。  
- 唯一寫入：本檔 + git commit。
