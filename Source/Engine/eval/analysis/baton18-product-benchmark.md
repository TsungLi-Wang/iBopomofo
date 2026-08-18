# 棒⑱ — Product Benchmark Construction

> **不修改 production、不 merge、不 enable、不接 app、不訓練模型、不新增 telemetry。**
> 個人輸入內容**只在本機處理**，未上傳、未送外部服務，
> **benchmark 檔案寫在 repo 之外**（`~/laowang-data/baton18-product-benchmark/`）。
> repo 內只留工具與統計，沒有任何原始輸入內容。

**標記**：`OBSERVED` ｜ `INFERRED` ｜ `NOT COMPUTABLE` ｜ `UNKNOWN` ｜
`USER_CORRECTION`（≠ linguistic gold）

---

## 0. 最重要的一句

**兩週 dogfood、584 行日誌，最後只有 15 筆是「引擎真的錯了、而且知道它原本選什麼」的事件。**
現有的紀錄機制**無法量測正確率**，只能量測錯誤的組成。

---

## PART 2 — Provenance / schema audit

### 兩個寫入點，語意完全不同（本棒最重要的 provenance 發現）

`ManualCorrectionLog.append` 有兩個呼叫端：

| 呼叫端 | `wrong_char` | `left_context` 的意義 | 能不能判定引擎錯了 |
|---|---|---|---|
| `KeyHandler.mm` `fixNodeWithReading`（打字中選字）| **空** | **選完之後的整串組字區 —— 含 `chosen` 本身** | ❌ 不能 |
| `InputMethodController+ShadowReselect.swift`（送出後重選）| `oldValue` | 真正的左文 | ✅ 能 |

⚠️ 第一種的 `left_context` **包含答案本身**。
任何未來拿這份資料訓練的人，如果直接把 `left_context` 當脈絡特徵，
就是**洩漏**。已寫進 `items.jsonl` 的 `left_context_semantics` 欄位。

### 兩種 schema

| schema | 欄位 | 行數 | provenance |
|---|---|---|---|
| v1 | `schemaVer \t ISO8601 \t reading \t left_context \t wrong_char \t chosen` | 399 | `OBSERVED`（原始碼註解定義）|
| v0（`272f46ee` 之前）| `ISO8601 \t reading \t left_context \t chosen` | 185 | **`INFERRED`** —— 185 筆中 184 筆的讀音音節數等於第 4 欄長度；時間上與 v1 乾淨切開（v0 08-04~08-06、v1 08-06~08-18）|

無法可靠解釋的欄位：**無**。無法解析的行：**4**。

---

## PART 3–4 — Canonical format 與分層

輸出 `~/laowang-data/baton18-product-benchmark/items.jsonl`，每筆含
`event_id`（sha256 前 12 碼）、`schema`、`provenance`、`timestamp`、`reading`、
`n_syllables`、`left_context`、**`left_context_semantics`**、`engine_output`、
`corrected_value`、**`label_status`**、**`gold_confidence`**、`tier`、`is_noop`、
`is_multi_char`、`touches_six_groups`、`exact_duplicate`、`content_duplicate_count`。

缺失欄位一律留 `null`／標記，**沒有補值**。

| 分層 | 定義 | 數量 | % |
|---|---|---:|---:|
| **A 可完整 replay** | 有 `wrong_char` **且** `wrong_char != chosen` | **15** | **2.6%** |
| A-noop | 有 `wrong_char` 但等於 `chosen` —— 使用者重選了同一個字，**不是引擎錯誤** | 13 | 2.2% |
| B 部分 replay | 無 `wrong_char`，不知道引擎原本選什麼 | 552 | 94.5% |
| C 不可 replay | 格式無法判定 | 4 | 0.7% |

**A-noop 這一層是本棒查出來的陷阱**：28 筆有 `wrong_char` 的事件裡，
有 **13 筆**（46%）使用者重選後跟原本一樣。
不排除的話會把可用樣本從 15 高估成 28。

---

## PART 5 — Benchmark split

**不切。** A 層只有 15 筆，切成 dev/test 沒有統計意義。

保留單一 `benchmark-all`，並明確標記：

> **sample size too small for independent test.**

本棒**沒有**發明複雜的 cross-validation。

---

## PART 9 — 標籤地位

所有事件的 `label_status` 一律是 **`USER_CORRECTION`**、
`gold_confidence` 一律是 **`unverified`**。

它是很有價值的產品訊號（使用者真的動手改了），
但**不是語言學金標**：沒有第二人核驗，也可能包含使用者自己改錯、
改成個人偏好用字、或誤觸。本棒**沒有**人工重判任何一筆。

---

## PART 6 — 使用者實際在修什麼

| 切面 | 值 |
|---|---|
| 日誌行數 | 584 |
| schema v1 / v0 | 399 / 185 |
| 時間範圍 | 2026-08-04 ~ 2026-08-18（約 2 週 dogfood）|
| 相異讀音 | 230 |
| 相異修正值 | 317 |
| 只出現一次的讀音 | 143（62.2% 的讀音）|
| 前 10 讀音佔事件 | 32.6% |
| 單字修正 | 488（84.1%）|
| 多字（詞級）修正 | 92（15.9%）|
| **涉及六組研究目標** | **72（12.4%）** |
| **六組以外** | **508（87.6%）** |
| 內容重複事件 | 262 |

⑮ 曾用「只讀 reading 欄」估六組佔 8.6%；本棒用實際的 chosen / wrong_char 字重算，得 **12.4%**。**以本棒為準。** 結論方向不變：絕大多數不在六組。


---

## PART 7 — Engine baseline（候選集來自 production 詞庫，未改引擎）

| 分層 | n | 修正目標在候選集 | 不在 | 修正目標＝詞頻第 1 | 中位詞頻名次 | 中位候選數 |
|---|---:|---:|---:|---:|---:|---:|
| 全部可解析 | 580 | 579（99.8%）| 1 | 277（47.8%）| 1 | 13 |
| **A 真正的引擎錯誤** | 15 | 15（100.0%）| 0 | 8（53.3%）| 0 | 48 |
| B 部分 replay | 552 | 551（99.8%）| 1 | 257（46.6%）| 1 | 13 |

### A 層 15 筆的分解

| 量 | 值 |
|---|---|
| 引擎輸出與修正目標**都在**候選集 → **純排序問題** | **15/15（100%）** |
| 修正目標不在候選集 → 候選生成問題 | **0/15（0%）** |
| 修正目標詞頻名次優於引擎輸出 | 8/15 |
| 修正目標＝詞頻第 1 名 | 8/15 |
| 引擎輸出＝詞頻第 1 名 | 3/15 |
| 相異 engine→corrected 方向 | **15 個 / 15 筆**（每個方向只出現 1 次）|
| 涉及六組 | 1/15 |
| 多字（詞級）| 0/15 |

---

## PART 8 — 第一版 Product KPI（定義）

| KPI | 定義 | 現況 | 可算嗎 |
|---|---|---|---|
| **Accuracy** | Engine top-1 == correction target | — | ❌ **`NOT COMPUTABLE`** |
| **Candidate coverage** | correction target 在 Engine 候選集內 | **99.8%**（579/580）；A 層 **100%** | ✅ |
| **Rescue opportunity** | 正解在候選集內但引擎沒選中 | **15/15（100% of A）** | ✅ |
| **Candidate-generation failure** | 正解不在候選集 | **0/15（0% of A）**；全體 1/580 | ✅ |
| **Damage** | 原本正確的決策被未來模型改錯 | 定義如左；本棒無新模型，**不計算** | 定義完成 |

### Accuracy 為什麼算不出來 —— 這是本棒最重要的量測結論

`manual-correction.log` **只在使用者動手修正時才寫入**。
它沒有記錄「引擎對了幾次」，也沒有任何送出總量的計數器
（`rerank-diff.log` 同理，只記重排有變動的 364 次）。

**沒有分母 → 正確率在結構上不可計算。**
這份日誌能回答「錯的長什麼樣」，**不能**回答「錯得多不多」。

---

## PRODUCT ERROR PRIORITY

只用實際觀測資料。分母是 580 筆可解析事件；「Engine failure」欄只有 A 層能判定。

| Error class | Count | % | Candidate available | Current Engine failure | Product priority |
|---|---:|---:|---:|---:|---|
| **排序錯誤**（正解在候選內、引擎選了別的）| **15** | 2.6% | **15/15（100%）** | **確認**（有 before/after）| **HIGH（唯一有直接證據的類別）** |
| 候選生成失敗（正解不在候選內）| **0** | 0.0% | — | 確認為 0 | **DROP**（本資料未觀測到）|
| 打字中選字（無法判定引擎是否錯）| 552 | 95.2% | 551/552（99.8%）| **`UNKNOWN`** | **INSTRUMENTATION**（要先能判定）|
| 使用者重選同一個字（no-op）| 13 | 2.2% | — | 非錯誤 | DROP |
| 格式不可解析 | 4 | 0.7% | — | `UNKNOWN` | DROP |
| （切面）多字／詞級修正 | 92 | 15.9% | 91/92 | A 層 **0/15** | MEDIUM（B 層佔比不低，但無法判定）|
| （切面）六組研究目標 | 72 | 12.4% | — | A 層 **1/15** | **LOW**（真實修正的 87.6% 在六組外）|

---

## PART 11 — 九個問題的答案

| # | 問題 | 答案 |
|---|---|---|
| 1 | 真實 correction dataset 有多少筆？ | 日誌 **584 行**，可解析 **580** |
| 2 | 有多少筆可以完整 replay？ | **15**（2.6%）—— 28 筆有 `wrong_char`，扣掉 13 筆 no-op |
| 3 | 有多少筆無法 replay？ | 552 部分 replay（無 `engine_output`）＋ 4 不可解析 |
| 4 | 真實使用者最常修什麼？ | **長尾。** 230 個相異讀音、62.2% 的讀音只出現一次、前 10 讀音只佔 32.6%；84.1% 是單字、15.9% 是詞級 |
| 5 | 六組研究目標佔多少？ | **12.4%**（⑮ 用只讀 reading 欄估 8.6%，本棒用實際字重算，以本棒為準）。**87.6% 在六組外** |
| 6 | Engine baseline accuracy？ | **`NOT COMPUTABLE`** —— 日誌只有錯誤、沒有分母 |
| 7 | Candidate coverage？ | **99.8%**（579/580）；A 層 **100%**（15/15）|
| 8 | 最大的 product error class？ | 就 A 層可判定的部分：**100% 是排序錯誤，0% 是候選生成失敗**。但 A 層只有 15 筆，**統計力極低** |
| 9 | 下一個模型應該優先攻哪一類？ | **一個都不要。** 見下 |

### 9 的完整回答

**現有真實資料還不足以指定任何模型方向。**

* A 層 15 筆、**15 個相異方向、每個方向只出現一次** —— 沒有任何可學的重複模式。
* 沒有正確率分母，無法算 net、無法算 damage、無法比較任何兩個方案。
* 樣本量小到連 dev/test 都不能切。

**下一步不是模型，是 instrumentation。**
目前 95.2% 的事件（552 筆）落在「打字中選字」路徑，
它**不記錄引擎原本選什麼**。如果那條路徑也記下 `wrong_char`
（引擎在該節點的 top-1），可用樣本會從 15 筆變成 500+ 筆量級。

⚠️ 這是**產品／隱私決策**，不是研究任務。
本棒**不修改 production、不新增 telemetry、不代為決定**，只把缺口指出來。

---

## Deferred（只記錄，不展開）

- **issue**：`KeyHandler` 路徑的 `left_context` 是「選完之後的組字區」，含 `chosen` 本身。
  **impact**：任何拿它當脈絡特徵的訓練都會洩漏。已在 `items.jsonl` 標旗標。
- **issue**：`lexicon_probe` 原本只輸出候選值不輸出分數，
  下游若據此談「名次」會建立在未驗證的假設上（實測 `data.txt` 本來就是 sorted 格式，
  所以順序恰好正確，但那是巧合不是保證）。本棒已改為輸出 `value:score`。
  ⑭-O 只用它判斷「在不在」，與順序無關，**結論不受影響**。
- **issue**：262 筆內容重複事件（同 reading/context/wrong/chosen）。
  可能是同一段文字反覆修改，也可能是重複觸發。未判定。
- **issue**：v0 schema 是推斷的（184/185 吻合），有 1 筆不吻合未查。
- **issue**：N=1 使用者、兩週。無法代表使用者群。

---

## 交付

| 項目 | 狀態 |
|---|---|
| production diff | **0** |
| frozen production files SHA256 | **未變** |
| merge / enable / 接 app / 正式 ship test | **全部 NO** |
| 訓練模型 | **NO** |
| 新增 telemetry | **NO** |
| 個人輸入內容進 repo | **NO**（benchmark 在 `~/laowang-data/baton18-product-benchmark/`）|
