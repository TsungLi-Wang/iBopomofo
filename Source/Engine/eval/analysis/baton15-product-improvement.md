# 棒⑮：從研究收斂到產品改善

> **純分析。不修改 production、不 merge、不 enable、不替換 production model、
> 不跑正式 test、不調 ship gate、不改 τ / ν / λ / `kNBestHypK`、
> 不新增 telemetry。**

**標記**：`OBSERVED` ｜ `COUNTERFACTUAL` ｜ `CROSS-FITTED` ｜ `NAIVE` ｜
`THEORETICAL / UPPER BOUND` ｜ `NOT COMPARABLE` ｜ `UNKNOWN` ｜
`CORPUS-LEVEL EVIDENCE` ｜ `REAL-USER (N=1)`

---

## 0. 一句話結論

**現有架構的三層 —— SEARCH、SCORING、NODE —— 全部量到頂了，
而且天花板都在「全語料字位的 0.1% 量級」。⑮ 判定 DROP，
但 C 找到一個真實訊號：使用者實際會去修的字，91.4% 不在我們研究了一整個系列的六組裡。**

| 層 | 已量到的 cross-fitted 上限 | 佔全語料字位 | 判定 |
|---|---|---|---|
| SEARCH（放寬 beam）| **+41 字** | 0.055% | 🔴 降為次要 |
| SCORING（重打分家族全體）| **+85 字** | 0.114% | 🔴 NO-GO |
| NODE Expert | +0.082% of D2 | 0.003% | 🔴 已於 ⑭-N/⑭-S DROP |
| （對照）top-10 可達 oracle | 1,198 字 | 1.60% | `THEORETICAL` |

---

---

## A — Beam / Search bounded audit

### A-0 Provenance

| 檢查項 | 結果 |
|---|---|
| `SENTENCES` | `SENTENCES 5976` |
| `K8_REPRODUCES_WALK` | `K8_REPRODUCES_WALK 5913 MISMATCH 63` |

本工具自行複製 `walkNBest()` 的 beam DP（`dp[pos][lastWord]` 每格留 K 個）。**K=8 必須逐句重現出貨輸出**。
已知偏差：引擎是**逐筆插入即裁切**，本工具是**累積後裁切**，在同分時保留的集合可能不同；另外本工具未複製 `forceTopUnigramOnly`（標點／字母讀音）與 node override —— 本語料無此類讀音。

**以下所有結論一律限制在「K=8 能重現出貨輸出」的句子上。**


可用句子 **5,919**／全部 5,976（99.0%）；其中 production 選錯的 **2,007** 句。



### A-1～A-3 gold path 在 beam 裡活到哪裡（K=8，出貨值）

| 狀態 | 句數 | % | 錯字 |
|---|---|---|---|
| gold 前綴**活到終點** | 850 | 42.4% | 1,016 |
| gold 前綴**中途被剪掉** | 1,157 | 57.6% | 2,131 |

被剪掉的那些，gold 前綴最後存活的位置（佔句長比例）：

| 分位 | 位置 / 句長 |
|---|---|
| P10 | 27% |
| P25 | 40% |
| **中位數** | 62% |
| P75 | 79% |
| P90 | 88% |

從未建立過 gold 前綴的句數：**0**（＝第一個字就沒進 beam）。

**A-3 的答案**：被排除的 beam state 是 `dp[位置][該位置的最後一個詞]` —— gold 前綴在該格的分數排不進前 K。


### A-4／A-5 放寬 K 的理論可救空間

| K | gold 活到終點 | gold 進得了出貨的前 10 條視窗 | rescue 字 | damage 字 | **net 字** | 佔 D2 | 佔全語料字位 |
|---|---|---|---|---|---|---|---|
| 8 ←出貨 | 850（42.4%）| 655（32.6%）| 0 | 0 | **+0** | +0.0% | +0.000% |
| 16 | 1,158（57.7%）| 709（35.3%）| 75 | 34 | **+41** | +1.3% | +0.055% |
| 32 | 1,397（69.6%）| 709（35.3%）| 75 | 34 | **+41** | +1.3% | +0.055% |
| 64 | 1,545（77.0%）| 709（35.3%）| 75 | 34 | **+41** | +1.3% | +0.055% |

⚠️ 這些是**放寬 beam 後、仍用現行出貨打分公式**重新選一次的結果，`COUNTERFACTUAL / OFFLINE ONLY`，不是 production 改動的預測值。


### A-6 成本（DP 邊評估次數，latency 的代理指標）

| K | 每句中位 edges | 相對 K=8 |
|---|---|---|
| 8 | 22,818 | **1.00×** |
| 16 | 44,251 | **1.94×** |
| 32 | 84,259 | **3.69×** |
| 64 | 159,575 | **6.99×** |

DP 邊數與 K 近似線性。實際 latency 還要加上 N-best 重排時的 RNN 呼叫，但重排視窗仍是 10 條，**RNN 成本不隨 K 增加**。


### A-7 事前判準

門檻：可救空間 **1% 全語料字位 = 746 字**（資源分流門檻，非統計顯著性門檻）。


實測最佳：**K=16，net +41 字**（rescue 75／damage 34）＝ D2 的 1.3%、全語料字位的 **0.055%**。


→ **< 1% → SEARCH 降為次要，不再作為第一 product intervention**

---

## B — LM / Path Scoring：量整個家族的天花板，而不是再做一個成員

### B-1 家族定義與 sanity check

`score = a·unigram + b·pmi + c·rnn`，候選集固定為 production 的 top-10。
出貨點 = (a,b,c) = (1.0, 1.0, 0.75)。網格 5,022 個權重組合。


**sanity check**：出貨點的 net = **+0** 字（必須為 0，否則重算與出貨不一致）。



### B-2 NAIVE 全域最佳（同一份語料掃出，**不得當結論**）

| | (a, b, c) | rescue | damage | net | precision | 字級正確率 |
|---|---|---|---|---|---|---|
| 出貨 | (1.0, 1.0, 0.75) | 0 | 0 | +0 | — | 95.707% |
| **NAIVE 最佳** | (1.0, 1.55, 2.3) | 209 | 113 | **+96** | 0.649 | 95.835% |


### B-3 CROSS-FITTED（document/句級 5-fold，4 選 1 評）

| | rescue | damage | net | precision | 佔 D2 | 字級 |
|---|---|---|---|---|---|---|
| **本棒：家族天花板** | 198 | 113 | **+85** | 0.637 | +2.7% | +0.114pp |
| ⑭-R（(α,ν) 2 維切片）| 177 | 108 | **+69** | 0.621 | +2.2% | +0.092pp |
| ⑭-S（learned MLP）| 239 | 186 | **+53** | 0.562 | +1.7% | +0.071pp |

逐 fold 選出的 (a,b,c)：(1.0, 1.5, 2.3)、(1.0, 1.55, 2.3)、(1.0, 1.4, 2.0)、(1.0, 1.4, 2.0)、(1.0, 1.4, 2.0)

**95% CI（document-cluster bootstrap，2,000 次）：[+42, +125]**


### B-4 逐句 oracle（每一句各自挑最有利的權重，`THEORETICAL UPPER BOUND`）

net = **687** 字（＝21.5% of D2）。
**這個數字不可達** —— 它允許每一句用不同的權重，而 production 只有一組全域權重。列出來只是為了界定家族的絕對上界。


### B-5 net 對 c（rnn 權重）的形狀，b 固定在出貨值 1.0

| c | rescue | damage | net |
|---|---|---|---|
| 0.00 | 168 | 2842 | **-2674** |
| 0.50 | 39 | 158 | **-119** |
| 0.75 ←出貨 | 0 | 0 | **+0** |
| 1.00 | 72 | 35 | **+37** |
| 1.50 | 147 | 83 | **+64** |
| 2.00 | 186 | 108 | **+78** |
| 3.00 | 215 | 148 | **+67** |
| 4.00 | 228 | 183 | **+45** |

---

## C — Minimum Product Benchmark：資料盤點

### C-1 現況：沒有 telemetry，但**已經有真實使用紀錄**

repo 內無 analytics、無上傳、無第三方 telemetry。
但 production 本身已經在**本機**寫兩份 append-only 紀錄（原始碼註解：
「Pure local append-only log under Application Support; **never uploaded**」）：

| 檔案 | schema（來自 `Source/ManualCorrectionLog.swift` / `RerankDiffLog.swift`）| 量 | 類別 |
|---|---|---|---|
| `manual-correction.log` | `schemaVer\tISO8601\treading\tleft_context\twrong_char\tchosen` | **584 事件** | **C Real-user (N=1)** |
| `rerank-diff.log` | `ISO8601\twalk\treranked` | 364 事件 | C（診斷用）|
| `user-override-cache.dat` | UserOverrideModel 持久化 | — | C（非 benchmark 格式）|

**本棒只讀了 schema（從原始碼）與聚合計數，未讀取 `left_context` /
`wrong_char` / `chosen` 的內容，也未把任何內容複製進 repo。**
那是使用者的個人輸入。

### C-2 只用 `reading` 欄的聚合統計（不暴露輸入內容）

| 量 | 值 |
|---|---|
| 事件數 | 584 |
| 相異讀音 | **298** |
| 多音節（詞級修正） | 63（10.8%）|
| **落在 ⑭ 研究的六組讀音** | **50（8.6%）** |
| 單一讀音最高頻次 | 31 |

**這是本棒最重要的產品訊號**：真實使用者實際會去修的字，
**91.4% 不在那六組裡**，而且是長尾（298 個讀音 / 584 次）。
⑭-M 在 PTT 語料上量到的 775 個方向長尾，在真實輸入上得到獨立佐證。

⚠️ **N = 1**（Johnny 自己 dogfood）。不是母體樣本，不能外推到使用者群。
標 `REAL-USER (N=1)`，與 `CORPUS-LEVEL EVIDENCE` **NOT COMPARABLE**。

### C-3 三類 benchmark 的現況（不得混算）

| 類別 | 資產 | 量 | 狀態 |
|---|---|---|---|
| **A Corpus** | 自然驗證集-真實語料（ptt-natural／ptt-minor）| 5,976 | ship-gate 正式測試集；⑭ 全系列的分析母體 |
| | X驗證集-真實語料（x-twitter）| 2,678 | ship-gate 正式測試集 —— **禁止觸碰** |
| | **獨立驗證集-真實語料（ptt-real）** | **1,657** | **非 ship-gate，⑭ 全系列從未使用** |
| **B Synthetic / controlled** | EX1166-全部（難題考卷）| 5,646 | 刻意堆難題，非出貨依據 |
| **C Real-user** | `manual-correction.log` | **584** | 已存在、不需新增 telemetry |

### C-4 DATA GAP 判定

**部分關閉。** 真實使用者 benchmark 的**資料來源已經存在**，
不需要新增 telemetry、不需要改 production。缺口是**量**（N=1、584 事件），
不是機制。

最小取得方式（**本棒不執行**，且屬產品／隱私決策而非研究任務）：

1. 就用現有的 `manual-correction.log`（零成本，已在本機）。
2. 若要擴大：由使用者**自行**決定是否匯出／分享自己的紀錄。
   **不得**由本專案自動收集、上傳、或新增任何 telemetry。
3. 不得用 PTT 語料偽裝成 production traffic。


---

## D — 三者對產品決策的意義

### D-1 三層為什麼全部封頂：同一個原因

```
                     全語料錯誤 D2 = 3,192（4.28% 字位）
                              │
        ┌─────────────────────┼─────────────────────┐
        │                     │                     │
     SEARCH                SCORING               NODE
   放寬 beam K            重打分家族           節點層專家
        │                     │                     │
   ceiling +41            ceiling +85          +0.082% of D2
   (0.055% 字位)          (0.114% 字位)         (⑭-K)
        │                     │                     │
        └─────────────────────┼─────────────────────┘
                              │
                    Product Benchmark（C）
                    真實修正 91.4% 在六組外
                              │
                              ▼
                          DROP
```

**A 的關鍵發現解釋了 B 為什麼也封頂**：把 K 從 8 放寬到 64，
gold 前綴活到終點的比例從 42.4% 升到 **77.0%** ——
但「gold 進得了出貨的前 10 條重排視窗」卻**從 K=16 起就停在 35.3%**，
net 也停在 **+41**。

原因是：終點清單是依 **walkScore（unigram ＋ λ·PMI）** 排序取前 10，
而 ⑭-T 已量到 walkScore 對 gold 的中位 Δ 是 **−1.06** ——
**打分器把 gold 擋在視窗外，所以搜尋找得再多也沒用。**

而 B 證明：整個「用現有 component 重打分」的家族，
cross-fitted 上限就是 **+85 字**。兩者合起來是同一句話：

> **瓶頸不在搜尋、不在候選、不在節點層，而在打分函數本身；
> 而現有 component 能組出來的打分函數已經到頂了。**

### D-2 為什麼不再做第四個 prototype

⑭-R（權重 2 維）、⑭-S（learned MLP）、本棒 B（權重 3 維全域上界）
是同一個家族的三個點：+69、+53、**+85（上界）**。
再做第四個成員，**數學上不可能超過 +85**。

依 §5 停止規則：家族已量到 intervention ceiling → 停止投入。

---

## E — 最終回答（七問）

| # | 問題 | 答案 |
|---|---|---|
| 1 | 第一個值得動的 production layer 是什麼？ | **沒有。** 現有架構三層全部封頂在 0.05–0.11% 字位量級 |
| 2 | 它的已知 ceiling 是多少？ | SEARCH +41 字（0.055%）／SCORING +85 字（0.114%）／可達 top-10 oracle 1,198 字（1.60%，`THEORETICAL`）|
| 3 | prototype 實際 net 是多少？ | ⑭-S MLP **+53**；本棒家族上界 **+85**（cross-fitted，CI [+42, +125]）|
| 4 | damage 是多少？ | 家族最佳點 **113 字**（precision 0.637）；⑭-S 186（precision 0.562）|
| 5 | 是否泛化？ | 是。⑭-S direction-held-out +34 未崩潰；本棒 cross-fitted 逐 fold 選出的權重穩定 |
| 6 | 真實 product benchmark 是否支持投入？ | **不支持。** N=1 的 584 次真實修正裡，**91.4% 不在六組**；而三層的可爭取量都在 0.1% 字位量級 |
| 7 | 下一步 | 🔴 **DROP** |

---

## F — GO BUILD / HOLD / DROP

### 🔴 DROP

對象是**現有架構內的三條 intervention 線**：

| 線 | 判定 | 依據 |
|---|---|---|
| SEARCH（放寬 beam / pruning）| **DROP 為次要** | +41 字 = 0.055% 字位 < 1% 門檻；K=64 要 7× DP 成本 |
| SCORING（任何用現有 component 的重打分）| **DROP** | 家族上界 +85，未明確高於 +69 baseline，CI [+42, +125] 涵蓋 baseline |
| NODE Expert | **維持 DROP** | ⑭-N / ⑭-S 已判；本棒未觸碰 |

**⑮ 到此結束。** 依 §5：三條都沒有足夠 ROI → 重新選另一個 error class。

### 這不是「輸入法沒救」

D2 只佔全語料字位的 **4.28%**；可達 top-10 oracle 是 **1.60%**。
被關掉的是「**在現有 decode → top-10 → 重排這條管線裡再擠一點**」這件事。
沒有被關掉的是：換一個更好的語言模型／解碼架構 ——
但那是**另一個量級的工程**，需要另立研究線，且本棒不建議也不啟動。

---

## G — 下一個「真正要寫 production code」的最小工程任務

**目前的證據不支持任何 engine 端的 production code 變更。**

若要寫 code，唯一有正當理由的是**量測基礎建設**，不是引擎：

> **把 `manual-correction.log` 變成可用的 benchmark 輸入。**

* 為什麼：C 顯示真實修正有 91.4% 落在六組外，而 ⑭ 全系列的分析母體是 PTT 語料的六組。
  **我們可能一直在最佳化錯的 8.6%。**
* 範圍：只需要 eval 端一支 loader（把 log 轉成既有的 `items.jsonl` 格式），
  **engine 端 0 行**。
* 不需要：新增 telemetry、上傳、改 production、改 ship-gate。
* 前提：使用者自己決定是否把自己的紀錄拿來當 benchmark。**本棒不代為決定、不代為執行。**

---

## H — Production integrity

| 項目 | 狀態 |
|---|---|
| production code 是否完全未動 | **是**（`git diff` 對追蹤檔為空）|
| 是否 merge | **否** |
| 是否 enable | **否** |
| 是否跑正式 test | **否**（自然驗證集只作為分析母體，未跑 ship-gate／model-ab；X驗證集完全未觸碰）|
| 是否改 `kNBestHypK` / ν / λ / τ | **否**（放寬 K 只發生在分析工具的記憶體裡）|
| 是否新增 telemetry | **否** |
| 是否讀取／複製使用者個人輸入內容 | **否**（只讀 schema 與 `reading` 欄的聚合計數）|

---

## I — Limitations

1. **A 的工具與引擎有 63/5,976（1.1%）不一致**（同分裁切順序），
   所有 A 的結論已限制在 K=8 能重現出貨輸出的 5,919 句上。
2. B 的家族只涵蓋**線性**組合；⑭-S 的非線性 MLP 實測 +53，低於線性上界 +85，
   但「所有非線性函數」的上界本棒未證明。
3. 放寬 K 的 net 是 `COUNTERFACTUAL`，不是 production 改動的預測值。
4. C 的真實資料 **N=1**，且只涵蓋這位使用者的輸入習慣與領域。
5. 語料側全部是 PTT，`NOT OBSERVED IN PRODUCTION TRAFFIC`；
   讀音由金標反查，詞庫缺字／注音打錯結構上不可見（⑭-O/⑭-T 已記錄）。
6. 本 dump 不含 `ParticleRuleDisambiguator`，與出貨路徑 `NOT COMPARABLE`。

---

## J — 資料出處

| 項目 | 出處 |
|---|---|
| beam survival 模擬（K = 8/16/32/64）| `bin/beam_survival_audit`（**本棒新增**）|
| beam 分析與判準 | `Source/Engine/eval/audit_beam_survival.py`（**本棒新增**）|
| 重打分家族天花板 | `Source/Engine/eval/audit_rescoring_family_ceiling.py`（**本棒新增**）|
| top-10 路徑分數 | `bin/path_score_dump`（⑭-Q／⑭-R）|
| 真實使用紀錄 schema | `Source/ManualCorrectionLog.swift`、`Source/RerankDiffLog.swift` |
| D2 = 3,192、LEXICON = 0 | `analysis/full-error-budget.md`（⑭-O）|
| 可達 top-10 oracle 37.5% of D2 | `analysis/full-corpus-nbest-oracle.md`（⑭-P）|
| walkScore Δ = −1.06、F = 26.7% | `analysis/gold-path-forced-score.md`（⑭-T）|
| baseline +69 / +53 | `analysis/path-score-symmetric-damage.md`（⑭-R）、`analysis/path-reranker-experiment.md`（⑭-S）|
| `kNBestHypK = 8` | `Source/Engine/gramambular2/reading_grid.h:368` |
