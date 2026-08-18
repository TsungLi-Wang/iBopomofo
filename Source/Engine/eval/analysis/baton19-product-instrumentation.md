# 棒⑲ — Product Error Instrumentation

> **工程交付棒。** 目標：在**不改變任何選字行為**的前提下，
> 補上「使用者修正前，引擎當時到底選了什麼」。
> 不訓練模型、不改 ranking / decoding / candidate generation / beam / LM、
> 不新增 telemetry、不上傳、不接雲端。

---

## 1. 現有 correction lifecycle

`ManualCorrectionLog.append` 有兩個呼叫端，語意完全不同：

| 路徑 | 位置 | 觸發時機 | 原本記到的 `wrong_char` |
|---|---|---|---|
| **A composing** | `KeyHandler.mm` `fixNodeWithReading` | 打字中從候選視窗選字 | **空** |
| **B reselect** | `InputMethodController+ShadowReselect.swift` `completeShadowRecomposePick` | 送出後重選 | `oldValue`（引擎原本的字）|

`fixNodeWithReading` 的實際順序是：

```
overrideCandidate(cursor, candidate)   ← 就地改 node 的 override
prevWalk = _latestWalk                 ← 只是複製 WalkResult
[self _walk]                           ← 重走
… 記 log
```

## 2. 原本的資料缺口

棒⑱ 量到：584 筆事件裡只有 **15 筆**可完整 replay，因為
**95.2% 走 composing 路徑，而那條路徑的 `wrong_char` 是空的**。
「引擎原本選什麼」在事後**無法還原** ——
`left_context` 記的是**選完之後**的組字區，反推等於用答案去猜。

### 一個必須講清楚的陷阱

不能在 `overrideCandidate` **之後**才去讀 `prevWalk`。

`WalkResult` 持有的是 `NodePtr`（`shared_ptr`），而
`overrideCandidate` → `Node::selectOverrideUnigram()` 是**就地修改同一個 node**。
`chosenValueAt()` 的優先序是「node override > DP > top unigram」，
所以在 override 之後讀 `prevWalk`，拿到的會是**使用者剛選的字**，
於是每一筆都會被標成 `NOOP_RESELECT`。

**擷取點因此必須在 `overrideCandidate` 之前。** 這是本棒實作上最關鍵的一行位置。

## 3. 新 instrumentation 放在哪裡

| 檔案 | 改動 |
|---|---|
| `Source/KeyHandler.mm` | 在 `fixNodeWithReading` **最上方、`overrideCandidate` 之前**，從 `_latestWalk` 讀出引擎當下的選擇，並用 `_grid->candidatesAt(cursor)` 取當下候選集（過濾成同一讀音、上限 16）。之後改呼叫 `appendV2`。 |
| `Source/InputMethodController+ShadowReselect.swift` | 改呼叫 `appendV2`，`engine_choice = oldValue`、`source = reselect`、候選集明確標為不可得（`-1`）。 |
| `Source/ManualCorrectionLog.swift` | 新增 schema v2 寫入器、純函式 `v2Line` / `classify`、共用 fail-open writer。v1 `append` 保留不動。 |

**只讀，不改決策**：新增的程式碼沒有呼叫 `walk`、沒有重新排序、
沒有動 override、沒有動候選生成。`candidatesAt()` 是候選視窗本來就會做的同一個
lattice 查詢，而且只在**明確選字時**執行一次，不在逐鍵路徑上。

## 4–5. 新 schema 與欄位語意

v2 是 **v1 版面的嚴格超集**（前 6 欄位置與意義對齊），依欄位數即可分派：

```
2 \t ISO8601 \t reading \t left_context \t engine_choice \t user_choice \t
event_type \t source \t candidate_count \t candidate_values
```

| 欄位 | 語意 |
|---|---|
| `schemaVer` | 固定 `2` |
| `ISO8601` | 事件時間 |
| `reading` | 讀音，多音節以 `-` 連 |
| `left_context` | **沿用 v1 語意，未擴大**：composing 路徑是選完之後的組字區、reselect 路徑是真正左文 |
| `engine_choice` | **引擎在決策當下自己選的值**。不可得時留空，**絕不用 `user_choice` 頂替、絕不事後反推** |
| `user_choice` | 使用者最後選的值 |
| `event_type` | `TRUE_CORRECTION` / `NOOP_RESELECT` / `UNKNOWN_ORIGINAL` |
| `source` | `composing` / `reselect` |
| `candidate_count` | 引擎當下提供的候選數；**`-1` = 明確不可得**。大於列出數即代表截斷 |
| `candidate_values` | 最多 16 個候選值，`\|` 連接；不可得時為空 |

欄位數：v2 = 10、v1 = 6、v0 = 4，**三者不撞**。

## 6. Privacy / data minimization

* **沒有新增任何自由文字欄位。** 新欄位只有兩個枚舉、一個整數、
  以及「同一個讀音底下的候選字」——那些字本來就在候選視窗上顯示給使用者看。
* `left_context` **維持原本行為，未擴大收集範圍**（棒⑲ 規則 §6）。
* 不記錄使用者帳號 / 姓名 / 任何識別資訊。
* **沒有網路傳輸、沒有雲端 analytics、沒有 backend**，沿用既有本機
  append-only 檔案（`~/Library/Application Support/iBopomofo/`）。
* 個人輸入內容**不進 repo**：測試全部用人工 fixture，
  benchmark 產物寫在 `~/laowang-data/baton18-product-benchmark/`。
* 寫入受 `Preferences.enableManualCorrectionLog` 控制（既有開關，未動）。

## 7. Backward compatibility

* v1 的 `append(...)` **原樣保留**，未刪除、未改簽名。
* v2 前 6 欄與 v1 對齊：`engine_choice` 就在 v1 的 `wrong_char` 位置、
  `user_choice` 就在 `chosen` 位置。舊 parser 讀前 6 欄仍得到相同語意。
* Loader 依欄位數分派 v2 / v1 / v0，實測同一個檔案混三種格式可正常解析：
  **v0 185、v1 399、v2 4**。

## 8. Tests

`McBopomofoTests/ManualCorrectionLogV2Tests.swift`，**11 項全綠**，
全部使用人工 fixture（無真實使用者內容）：

| 測試 | 對應 Gate |
|---|---|
| `testTrueCorrectionKeepsEngineChoice` | Gate 2 |
| `testNoopReselectIsNotAnError` | Gate 3 |
| `testUnknownOriginalIsNeverGuessed` | §七 C |
| `testCandidateSetIsRecoverable` | Gate 4 |
| `testCandidateUnavailableIsExplicit` | Gate 4（不可得的情形）|
| `testCandidateTruncationStaysVisible` | 截斷可偵測 |
| `testMultiSyllableReading` | 多音節 |
| `testSeparatorsAreEscapedSoOneEventIsOneLine` | 格式健全性 |
| `testEmptyReadingOrChoiceIsRejectedByClassifierContract` | 空讀音 |
| `testSchemaVersionsAreDistinguishable` | Gate 5 |
| `testV2IsSupersetOfV1Layout` | Gate 5 |

## 9. Behavior equivalence（Gate 1）

**完整既有測試套件 165 項全綠**（含 `CommitContractGoldenTests`、
`KeyHandlerBopomofoTests`、`ContextualWalkPunctuationRegressionTests`）。

論證：新增碼在 `overrideCandidate` 之前執行且**只讀**
（`findNodeAt` / `chosenValueAt` / `candidatesAt` 皆為查詢），
結果只流向 log 呼叫，不回寫 grid、不影響 `overrideCandidate` 的輸入、
不影響其後的 `_walk`。

## 10. Fail-open（Gate 6）

實作時發現原本的 writer **不是** fail-open：
`FileHandle.write(_:)` 在寫入失敗（磁碟滿、權限被撤）時會拋 **ObjC 例外**，
Swift 接不到 —— 那會讓一個診斷用 log 弄掛輸入法。

已改用會拋 Swift error 的 `seekToEnd()` / `write(contentsOf:)` 並 `catch` 後丟棄。
現在每一條失敗路徑都是提早 return：
`Preferences` 關閉、`reading`/`userChoice` 為空、UTF-8 轉換失敗、
`FileHandle` 開不起來、seek/write 拋錯 —— 全部靜默返回，
`appendV2` 回傳 `Void`，呼叫端不檢查結果。

（v1 `append` 現在共用同一個 writer，等於一併修好。）

## 11. Candidate coverage

composing 路徑會記錄候選集；reselect 路徑（送出後）此處沒有 live lattice，
**明確標為不可得（`-1`）而不是猜或重跑一次候選生成**。

實機已產生 4 筆 v2 事件（測試 host app 執行期間），結構如下：

| event_type | source | engine_choice 有值 | candidate_count | user_choice 在候選內 |
|---|---|---|---|---|
| TRUE_CORRECTION ×4 | composing | 是 ×4 | 2 | 是 ×4 |

→ **composing 路徑不再是 `UNKNOWN_ORIGINAL`**，Gate 2 在真實執行下驗證通過。

## 12. 已知限制

* reselect 路徑沒有候選集（明確標記，非猜測）。
* `left_context` 在 composing 路徑仍是「選完之後」的組字區。
  **未來若要用它當脈絡特徵，會洩漏答案** —— 本棒刻意不擴大它的收集範圍，
  loader 的 `left_context_semantics` 欄位把這件事標出來。
* v0 的 schema 是結構推斷（184/185 吻合），非原始碼定義。
* 本機事件量仍小；instrumentation 只是讓未來累積的資料可用，
  **不會回填已經記錄過的 552 筆 `UNKNOWN_ORIGINAL`**。

## 13. Production impact

| 項目 | 狀態 |
|---|---|
| 選字結果 / ranking / candidate generation / decoding / LM / beam | **未改** |
| 已安裝的輸入法 | **未替換**（`~/Library/Input Methods/iBopomofo.app` 仍是既有 build）|
| merge / enable / 接 app / 正式 ship test | **全部 NO** |
| 新增 runtime / network 依賴 | **無** |
| 逐鍵延遲 | 未增加（新增碼只在明確選字時執行一次）|

## 14. 怎麼把 log 轉成 `items.jsonl`

```bash
python3 Source/Engine/eval/build_product_benchmark.py \
    --log ~/Library/Application\ Support/iBopomofo/manual-correction.log \
    --out ~/laowang-data/baton18-product-benchmark
```

Loader 支援 v0 / v1 / v2，輸出含 `schema`、`event_type`、`source`、
`engine_output`、`corrected_value`、`candidate_count`、`candidate_values`、
`candidate_truncated`、`user_choice_in_candidates`、`label_status`、
`gold_confidence`、`tier`，並印出 schema 分布、event_type 分布、candidate coverage。

**輸出目錄硬性檢查不得在 repo 內**（個人輸入內容不進 repo）。

## 15. 未來可以從這份資料回答哪些產品問題

* 引擎實際選錯的方向分布（`engine_choice → user_choice`）
* 真正的修正 vs 只是重選同一個字（TRUE_CORRECTION vs NOOP_RESELECT）
* 使用者最後選的字有沒有在候選集裡（候選生成 vs 排序）
* 錯誤集中在哪些讀音、單字還是詞級
* 兩條 correction 路徑的相對頻率

---

## 最後一節

**這份 instrumentation 不會告訴我們模型該怎麼改；
它只會讓我們第一次能可靠地知道產品實際錯在哪裡。**

它不產生任何模型結論，也不指定下一個研究方向。
它只是把「引擎原本選了什麼」這件事，從**事後無法還原**變成**當下就記下來**。

## Deferred / Future Research

- **issue**：`left_context` 在 composing 路徑含答案本身，任何拿它當特徵的訓練都會洩漏。
  未來若要真的可用，需要另外記「修正前」的左文 —— 本棒**未做**（會擴大資料收集）。
- **issue**：552 筆歷史 `UNKNOWN_ORIGINAL` 無法回填。
- **issue**：沒有正確率分母（日誌只在修正時寫入），accuracy 仍 `NOT COMPUTABLE`。
  要解需要另一種計數器，屬產品／隱私決策。
- **issue**：`ManualCorrectionLog.logFilePath` 不可注入，fail-open 只能以程式碼結構論證，
  無法在測試中真的模擬寫入失敗。
