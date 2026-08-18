# Gold Path Forced-Score Diagnostic（棒⑭-T · 2026-08-18）

> **純分析。不訓練、不改 production、不放寬 beam、不改 `kNBestHypK`、
> 不改 ν / λ / 權重 / 候選生成 / 搜尋深度、不跑正式 test、不 merge、不 enable。**

**標記**：`OBSERVED` ｜ `COUNTERFACTUAL` ｜ `THEORETICAL / UPPER BOUND` ｜
`NOT COMPARABLE` ｜ `UNKNOWN` ｜ `CORPUS-LEVEL EVIDENCE`

---

## 1. Executive Summary

**判定：MIXED**（事前門檻：20% ≤ F < 40%）。**F = 26.7%**

1. **在 production 選錯的 2,042 句裡，只有 26.7%（545 句）出貨打分器
   其實更喜歡 gold path**；**73.3%（1,497 句）打分器明確偏好錯的那一條。**
2. **換算成錯字**：GOLD_BEATS_TOP1 涵蓋 **984 字＝ D2 的 30.8%＝
   全語料字位的 1.32%**；GOLD_LOSES 涵蓋 2,221 字＝ D2 的 69.6%。
3. **那 26.7% 幾乎全是搜尋側的**：其中 **87.9%（479 句）連 200 條枚舉裡都沒出現**，
   12.1%（66 句）出現在第 11–200 條、被出貨的 10 條重排視窗擋在外面，
   **0 句**落在出貨實際打分的前 10 條內（與恆等式一致，見 §6）。
4. **成分拆解給出一個很乾淨的分工**：
   在 GOLD_BEATS_TOP1 裡，`walkScore`（unigram ＋ λ·PMI）**反對** gold（中位 −1.059），
   是 **ν·rnn 把它救起來的**（中位 **+2.488**）。
   在 GOLD_LOSES 裡則是兩者都反對（−1.021 / −0.238）。
   **神經語言模型是唯一站在 gold 那邊的力量；詞頻先驗一路都在反對。**
5. **⑭-P 的 43.1% 必須重讀**：`walkNBest(200)` 實際只回傳**中位 66 條**，
   只有 16.6% 的句子拿滿 200 條。詳見 §9 的 LIMITATION / CORRECTION。

**一句話**：**約四分之三的 production 錯誤，是打分器真的比較喜歡錯的那一句；
剩下四分之一裡，絕大多數是 gold 根本沒被枚舉出來。兩層都有責任，不能歸給單一層。**

---

## 2. Provenance audit（不通過就停，不繼續分析）

| 檢查項 | 結果 |
|---|---|
| 獨立重算 `Σ unigram + Σ λ·PMI` ＝ `RankedPath::walkScore` | `PROV_WALKSCORE_MATCH 508592 / 508592` |
| 重算的 top-1（前 10 條 fused argmax）逐字等於 `walk()` 輸出 | `TOP1_REPRODUCES_WALK 5976 MISMATCH 0` |
| gold path 無法構造的句數 | `GOLD_PATH_NOT_CONSTRUCTIBLE 0` |
| 處理句數 | `SENTENCES 5976` |

出貨配置：λ=0.75、ν=0.75、rerank N-best=10、adjust=0（`confusionAlphas_` 未設）。
公式照抄 `reading_grid.cpp`：`walkScore = Σ unigram.score() + Σ contextModel->scoreWithReading(...)`、`fused = walkScore + ν·rnn`。

gold 只用來**構造被測量的物件**與判定命中，**不進入任何 feature、不改變任何分數的算法**。



## 3. 母體（單位講清楚）

| 單位 | 量 | 標記 |
|---|---|---|
| **primary unit：句** | production 選錯的句子 **2,042** | `OBSERVED` |
| 其中 gold path 可構造 | **2,042**（100.0%）| `OBSERVED` |
| **secondary unit：字** | 這些句子的 walk 錯字 **3,205** | `OBSERVED` |
| 全語料 D2 | 3,192 | ⑭-O/⑭-P |
| 全語料字位 | 74,649 | ⑭-O |

句數與錯字數是兩個不同的單位，本報告一律分開報。



## 4. 主分類與 PRIMARY KPI

| classification | count | % |
|---|---|---|
| **GOLD_BEATS_TOP1** | **545** | **26.7%** |
| TIE | 0 | 0.0% |
| GOLD_LOSES | 1,497 | 73.3% |

### PRIMARY KPI

**F = 545 / 2,042 = 26.7%**（`SCORER-FAVORABILITY`）

⚠️ F **不是** rescue rate、**不是** beam failure rate、**不是** recoverable rate。gold 分數較高，不代表放寬 beam 就枚舉得到它。



## 5. 三個分母

| 量 | 句比例 | 錯字數 | 佔 D2 | 佔全語料字位 |
|---|---|---|---|---|
| **GOLD_BEATS_TOP1** | 26.7% | 984 | **30.8%** | **1.32%** |
| GOLD_LOSES | 73.3% | 2,221 | 69.6% | 2.98% |
| TIE | 0.0% | 0 | 0.0% | — |


## 6. GOLD_BEATS_TOP1 再分層（enumerated / pruned）

「production 實際打分的集合」＝ `walkNBest(10)`（出貨 `setPathRerankNBest(10)`）。`walkNBest(200)` 只是本棒為了檢查枚舉而多跑的，**不是**出貨行為。


| 子集 | count | % of GOLD_BEATS_TOP1 | 佔 D2 |
|---|---|---|---|
| **ENUMERATED + SCORE_WRONG**（gold 在出貨的前 10 條內） | 0 | 0.0% | 0.0% |
| 在 11–200 條內（出貨重排視窗看不到） | 66 | 12.1% | 2.6% |
| **PRUNED_OR_UNENUMERATED**（200 條內都沒有） | 479 | 87.9% | 28.3% |
| UNKNOWN | 0 | 0.0% | 0.0% |

**`ENUMERATED + SCORE_WRONG` 必然為 0**：top-1 就是那 10 條的 fused argmax，gold 若在其中且分數更高，它就會是 top-1。實測 0，與這個恆等式一致 —— 這是一個內部一致性檢查。



## 7. Δ_gold = score(gold) − score(top-1) 分布

| 分位 | GOLD_BEATS_TOP1 | GOLD_LOSES |
|---|---|---|
| P10 | +0.202 | -4.021 |
| P25 | +0.588 | -2.259 |
| **中位數** | +1.202 | -1.142 |
| P75 | +2.177 | -0.486 |
| P90 | +3.528 | -0.178 |
| n | 545 | 1,497 |

不報平均數（長尾）。


## 8. Δ 的成分拆解：是 walkScore 還是 rnn 在做決定

| 子集 | Δ walkScore 中位 | Δ ν·rnn 中位 | Δ fused 中位 |
|---|---|---|---|
| GOLD_BEATS_TOP1 | -1.059 | +2.488 | +1.202 |
| GOLD_LOSES | -1.021 | -0.238 | -1.142 |


## 9. LIMITATION / CORRECTION：⑭-P 的 43.1% 要怎麼重讀

中位數 **66** 條；滿 200 條的只有 16.6%。
這正是 ⑭-P 的 43.1% 不能當作 exact 200-best 排名的原因。

### ⑭-P 原結果不刪除，但加上這條限制

⑭-P 報的：

| 深度 | % of D2 |
|---|---|
| top-10 | 51.8% |
| top-20 | 55.8% |
| top-200 | 56.9% |
| **> 200** | **43.1%** |

**這些數字本身沒有錯**（它們忠實描述「`walkNBest` 在出貨配置下實際枚舉到的路徑」），
但 **`> 200` 不能讀成「打分器把 gold 排到第 201 名以後」**：

* `walkNBest()` 是 **beam DP**，`reading_grid.h` `kNBestHypK = 8` ——
  每個 (位置, 前一個詞) 狀態只保留 8 個 hypothesis。
* 實測：向它要 200 條，**中位只回傳 66 條**，只有 **16.6%** 的句子拿滿 200。
* 所以那 43.1% 是「**沒被枚舉到**」與「**排名真的很後面**」的混合，
  ⑭-P 當時無法區分。

**本棒就是為了解開這個 ambiguity。** 解開後的答案在 §4–§6：
在 production 選錯的句子裡，打分器其實偏好 gold 的只有 26.7%，
而那 26.7% 裡有 87.9% 從未被枚舉。

---

## 10. 按錯誤類型分層

`NOT_AVAILABLE`。

⑭-O 的 `NODE` / `PATH-SEG` 分類是**逐字**（每個錯字所在節點的候選是否含金標），
本棒的分析單位是**逐句**（整條 gold path 的分數）。
一句可能同時含 NODE 與 PATH/SEG 的錯字，無法可靠映射成單一句級標籤。

依規定**不重新發明分類**，此欄標 `NOT_AVAILABLE`。

---

## 11. ROI 限制（兩個分母同時看）

| 量 | 錯字 | 佔 D2 | 佔全語料字位 |
|---|---|---|---|
| D2（全部 walk 錯字）| 3,192 | 100% | **4.28%** |
| GOLD_BEATS_TOP1（打分器偏好 gold）| 984 | 30.8% | **1.32%** |
| 　└ 其中從未被枚舉 | **902** | 28.3% | 1.21% |
| 　└ 其中在 11–200 條 | **82** | 2.6% | 0.11% |
| GOLD_LOSES（打分器偏好錯的）| 2,221 | 69.6% | **2.98%** |

**即使 beam / search 相關的那一塊全部解決，可觀測的改善空間也只有
全語料字位的 1.32%。** 不能說「beam 是輸入法最大的問題」——
最大的那一塊是 **GOLD_LOSES 的 2.98%**，那是打分器／語言模型的問題。

（`984 + 2,221 = 3,205`，比 D2 的 3,192 多 13：全部來自 sid 1517 一句，
walk 輸出長度與金標不等，⑭-M/⑭-P 依慣例整句排除，本棒的 dump 以
`e = 金標長度 = 13` 計入。⑭-S §10 已記錄，兩者 `NOT COMPARABLE`。）

---

## 12. 詞庫限制（維持 ⑭-O 的原始限制，不得放寬）

`GOLD_PATH_NOT_CONSTRUCTIBLE = 0` —— 5,976 句的 gold path **全部可構造**。

**這不能寫成「production 沒有 lexicon 問題」。** 只能寫：

> **本 corpus 未觀測到 lexicon absence。**

理由（⑭-O 已記錄，本棒重申）：這份語料的 `full_reading` 是**從 gold sentence
逐字對齊取得**的，所以每個金標字必然在它自己的讀音下查得到。
本語料**結構上無法觀測**：詞庫缺字、新詞、人名、未知詞、
使用者注音輸入錯誤、真實 typing traffic。

同理，**不得因為 gold path 可以被強制構造，就聲稱「candidate generation 沒問題」** ——
gold path 是 counterfactual 物件；production beam 能不能自然產生它是**另一個問題**，
而 §6 顯示：87.9% 的 GOLD_BEATS_TOP1 案例，它**沒有**被產生出來。

---

## 13. 最終判定

| 事前門檻 | 條件 | 實測 | 命中？ |
|---|---|---|---|
| BEAM/SEARCH RESEARCH | F ≥ 40% | 26.7% | ❌ |
| **MIXED** | **20% ≤ F < 40%** | **26.7%** | ✅ |
| SCORER/LM RESEARCH | F < 20% | 26.7% | ❌ |

**→ MIXED。**

門檻未修改，未事後調整，未自行提出第五種分類。

依 §10 的規定，MIXED 代表：**不能把問題歸因給單一層**，
下一步必須再做 gold-path beam survival / pruning-stage 分析。
**本棒不做，也不啟動。**

必附項目：

* **F** = 26.7%（545 / 2,042）
* **D2 share** = 30.8%（984 / 3,192）
* **全語料 share** = 1.32%（984 / 74,649）
* **enumerated / unenumerated breakdown**：前 10 條內 0（0.0%）／
  11–200 條 66（12.1%）／未枚舉 479（87.9%）／UNKNOWN 0
* **provenance**：walkScore 重算 508,592/508,592、top-1 重現 5,976/5,976、
  gold path 不可構造 0
* **limitations**：§9（⑭-P 重讀）、§10（分層 `NOT_AVAILABLE`）、
  §11（ROI 兩個分母）、§12（詞庫與 candidate generation 不得偷渡）

---

## 14. 最後一句話的回答

> 「在 production 選錯的案例中，究竟有多少比例是 scorer 明確偏好錯誤 top-1，
> 而不是 gold path 被 beam / search 排除？」

**73.3%（1,497 / 2,042 句，涵蓋 D2 的 69.6%）是 scorer 明確偏好錯誤 top-1。**
剩下 26.7% 打分器其實偏好 gold，但其中 **87.9% 的 gold path 從未被枚舉**。

**判定：MIXED。**

---

## 15. 不做下一步

依 §23，即使 MIXED 也不得：放寬 beam、改 `kNBestHypK`、重跑正式 test、
訓練 LM、訓練 reranker、修改 production。本棒**只報判定，不啟動任何後續實驗**。

---

## 16. Unknowns

1. **MIXED 的兩層各自的真實可救量** —— F 只是 `SCORER-FAVORABILITY`，
   不是 recoverable rate。那 479 句未枚舉的，放寬 beam 後**能不能真的枚舉到**，
   `UNKNOWN`（需要 beam survival 分析，本棒不做）。
2. 即使枚舉到了，**選不選得中是另一回事** —— ⑭-S 剛給了 fixed-top-10 reranking NO-GO。
3. `walkScore` 反對 gold（中位 −1.059）而 `ν·rnn` 支持（+2.488）——
   這個張力在放寬 beam 後會如何變化，`UNKNOWN`。
4. GOLD_LOSES 那 69.6% 的成因（LSTM 容量？訓練語料？詞頻先驗？），`UNKNOWN`。
5. 真實打字流量：完全沒有資料。全部為 `CORPUS-LEVEL EVIDENCE`（PTT）。
6. 本 dump 不含 `ParticleRuleDisambiguator`，與出貨路徑 `NOT COMPARABLE`。

---

## 17. Production integrity

| 項目 | 狀態 |
|---|---|
| `kNBestHypK` / beam / pruning / `walk()` / `walkNBest()` | **未動** |
| ν / λ / unigram / RNN / PMI 權重 / 候選生成 / 搜尋深度 | **未動** |
| `path-char-lstm.bin` / `NodeHomophoneExpert.*` / `KeyHandler.mm` | **未動** |
| 訓練 / merge / enable / 接 app / 正式 test | **全部未做** |
| 新增 | 一支唯讀分析工具與一支分析腳本 |

---

## 18. 資料出處

| 項目 | 出處 |
|---|---|
| gold path 強制構造與打分（5,976 句）| `bin/gold_path_score`（**本棒新增**）|
| 統計與判定 | `Source/Engine/eval/audit_gold_path_score.py`（**本棒新增**）|
| gold 是否在出貨前 10 條 | `paths-all.tsv`（⑭-Q `bin/path_score_dump`、⑭-R `all=1`）|
| 融合公式與 beam 常數 | `Source/Engine/gramambular2/reading_grid.cpp` / `reading_grid.h:368` |
| D2 = 3,192、LEXICON = 0 | `analysis/full-error-budget.md`（⑭-O）|
| top-200 覆蓋 56.9%、43.1% absent | `analysis/full-corpus-nbest-oracle.md`（⑭-P）——本棒 §9 加限制 |
| fixed-top-10 reranking NO-GO | `analysis/path-reranker-experiment.md`（⑭-S）|
