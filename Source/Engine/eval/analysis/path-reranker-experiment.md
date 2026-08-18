# Learned Path Reranker 實驗（棒⑭-S · 2026-08-18）

> **一次性研究實驗。禁止 merge / enable / 接 app / 跑正式 test / 改 production。**
> 訓練的是**研究用**權重，不匯出任何可上線格式，不動 `path-char-lstm.bin`、
> `walk()`、`walkNBest()`、候選生成、ν、λ、τ、`ParticleRuleDisambiguator`。
> 候選集**完全固定**為 production 已產生的 top-10 路徑。

**標記**：`OBSERVED` ｜ `CROSS-FITTED` ｜ `COUNTERFACTUAL` ｜
`THEORETICAL / UPPER BOUND` ｜ `NOT COMPARABLE` ｜ `UNKNOWN`

---

## 1. Executive Summary

**判定：🔴 NO-GO。**（事前 gate：`net ≤ +69` → NO-GO。實測 **+53**。）

1. **learned reranker 沒有突破權重上限。**
   cross-fitted net **+53 字**，95% CI（document-cluster bootstrap）**[+3, +99]**。
   ⑭-R 的 `CROSS-FITTED COUNTERFACTUAL BASELINE` 是 **+69**。
   CI 涵蓋大量低於 69 的值 → **不支持「突破 baseline」**。
2. **它救得比較多，但壞得更多。**
   rescue 239（baseline 177）、damage 186（baseline 108）、
   precision **0.562**（baseline 0.621）。**交易條件變差了。**
3. **排序指標確實變好，但沒有換成 net。**
   top-1 0.849 → **0.857**、MRR 0.914 → **0.920**、pairwise 0.973 → **0.976**。
   這是 ⑭ 系列**第四次**示範「ranking metric ≠ system net」
   （⑭-K 節點層、⑭-N 泛化、⑭-R 權重、本棒）。
4. **一個真正的正面發現：路徑層沒有 ⑭-N 的方向崩潰。**
   direction-held-out 診斷下仍是 **+34**（rescue 251 / damage 217）。
   節點層在同樣的壓力測試下條件 AUC 崩到 0.459（低於隨機）。
   **路徑層的訊號是跨方向的，不是方向記憶** —— 這個結論本棒予以確認。
5. **天花板檢查通過**：+53 遠低於 ⑭-P 的可達 top-10 oracle
   **1,198 字（37.5% of D2）**，無需 provenance audit。

**一句話**：在固定 top-10 候選集下，learned path reranker
**沒有**突破 +69 的權重上限；它把 rescue 與 damage 一起放大，淨值反而略降。

---

## 2. Feature provenance / leakage audit（只有 available_at_inference = YES 才進模型）

| feature 群 | source | available at inference? | training-only? | gold-dependent? | leakage risk |
|---|---|---|---|---|---|
| walk_score（原始／減最大／z／句內名次／每字）| ReadingGrid DP 分數 | **YES** | NO | **NO** | 無 —— 只由 10 條路徑本身算出 |
| unigram_sum（原始／減最大／z／句內名次／每字）| 節點 unigram 總和 | **YES** | NO | **NO** | 無 —— 只由 10 條路徑本身算出 |
| pmi（原始／減最大／z／句內名次／每字）| CorpusBigramContextModel | **YES** | NO | **NO** | 無 —— 只由 10 條路徑本身算出 |
| rnn（原始／減最大／z／句內名次／每字）| NeuralLMPathScorer | **YES** | NO | **NO** | 無 —— 只由 10 條路徑本身算出 |
| fused（原始／減最大／z／句內名次／每字）| walkScore + ν·rnn（出貨分數） | **YES** | NO | **NO** | 無 —— 只由 10 條路徑本身算出 |
| dp_rank、dp_rank_is0 | `walkNBest` 回傳順序 | **YES** | NO | **NO** | 無 |
| log_len、n_paths | 讀音長度、候選數 | **YES** | NO | **NO** | 無 |

共 **29** 維。**明確排除**：corpus gold、gold 字、gold path 身分、`gold_rank`（offline-only）、人工標註、未來字、以 gold 重新斷詞的任何量。


`is_gold` 只用於 (a) 造 training pair、(b) 評分，**未進入 feature**。


## 3. 資料集與 fold 建構

* 句子 **5,976**（＝文件；一句一個 `doc_id`）
* ENGINE-CORRECT 3,934 ／ ENGINE-WRONG 2,042
* **gold path ∈ top-10 的 4,634 句可造 pair**；其餘 1,342 句標 `GOLD_ABSENT_FROM_TOP10`，**不進 training**，只進評估與 ceiling
* fold ＝ `sha256(f"baton14f-fold-v1:{doc_id}")[:8] % 5`（canonical，未重新設計）

| fold | 句數 | 可訓練句 | ENGINE-WRONG |
|---|---|---|---|
| 0 | 1,144 | 879 | 378 |
| 1 | 1,170 | 880 | 429 |
| 2 | 1,226 | 950 | 429 |
| 3 | 1,174 | 925 | 398 |
| 4 | 1,262 | 1,000 | 408 |


## 4. Cross-fitted 主結果

| 量 | 值 |
|---|---|
| 現況 walk 錯字（D2）| 3,205 |
| reranker 後錯字 | 3,152 |
| **rescue（字）** | 239 |
| **damage（字）** | 186 |
| **net（字）** | **+53** |
| rescue precision | 0.562 |
| 字級正確率 | 95.707% → **95.778%** |
| 整句由錯轉全對 | 137 |
| 整句由全對轉錯 | 99 |
| 佔 D2 | +1.7% |

**95% CI（document-cluster bootstrap，2,000 次）：[+3, +99]**


## 5. 與 ⑭-R 的 side-by-side

| | ⑭-R baseline | ⑭-S reranker |
|---|---|---|
| 方法 | `CROSS-FITTED COUNTERFACTUAL`（掃 ν′）| `CROSS-FITTED` learned MLP |
| rescue | 177 | 239 |
| damage | 108 | 186 |
| **net** | **+69** | **+53** |
| precision | 0.621 | 0.562 |
| char accuracy | 95.799% | 95.778% |
| 95% CI | 未算（點估計）| [+3, +99] |

⚠️ baseline 是 `CROSS-FITTED COUNTERFACTUAL`，**不是 production 結果**。


## 6. Ranking metrics（secondary，不得取代 net）

| 指標 | 現有 fused | reranker |
|---|---|---|
| top-1 accuracy | 0.849 | **0.857** |
| top-2 accuracy | 0.954 | **0.962** |
| MRR | 0.914 | **0.920** |
| pairwise accuracy | 0.973 | **0.976** |

（母體：gold ∈ top-10 的 4,634 句。現有 fused 的 top-1 = 引擎解對率，非獨立指標。）

## 7. 逐方向：cross-fitted reranker 的 rescue / damage

| 首個錯字方向 | 句數 | rescue 字 | damage 字 | net | 判讀 |
|---|---|---|---|---|---|
| 在→再 | 108 | 33 | 2 | **+31** | 正 |
| 做→坐 | 66 | 10 | 1 | **+9** | 正 |
| 他→她 | 51 | 5 | 2 | **+3** | 正 |
| 啊→阿 | 49 | 4 | 1 | **+3** | 正 |
| 作→做 | 32 | 4 | 1 | **+3** | 正 |
| 作→座 | 28 | 0 | 1 | **-1** | 負 |
| 前→錢 | 28 | 7 | 2 | **+5** | 正 |
| 做→作 | 23 | 2 | 0 | **+2** | 正 |
| 板→版 | 23 | 5 | 1 | **+4** | 正 |
| 掛→卦 | 23 | 2 | 0 | **+2** | 正 |
| 教→叫 | 21 | 1 | 0 | **+1** | 正 |
| 什→甚 | 19 | 0 | 11 | **-11** | 負 |

方向共 966 個，其中 942 個 n<10 標 **INSUFFICIENT POWER**（保留）；它們合計 rescue 147、damage 45、net +102。
n≥10 的方向共 24 個，其中 **4 個淨為負**。


## 8. Direction-held-out diagnostic（同一模型／特徵／objective，只換切分）

⑭-N 的失敗模式是「方向記憶」。這裡把切分改成 direction-held-out，
確認 reranker 是不是也只在看過的方向上有效。**不是重新訓練 production**，
也**不用它取代主結果** —— 主結果仍是 document-level 5-fold 的 +53。

| 切分 | rescue | damage | net |
|---|---|---|---|
| document-held-out（主結果）| 239 | 186 | **+53** |
| **direction-held-out**（診斷，修正版）| 251 | 217 | **+34** |

⑭-N 的節點層在 direction-held-out 下條件 AUC 崩到 0.459（低於隨機）。

---

## 9. 訓練協定（實際執行的，未事後更動）

| 項目 | 設定 |
|---|---|
| 模型 | 單隱藏層 MLP：`Linear(d→32) → Tanh → Linear(32→1)`，輸出 scalar path score |
| objective | **pairwise logistic**（`softplus(-(s_gold − s_neg))`），只用這一種 |
| 決策規則 | **純 `argmax`**，不引入任何 threshold、不做 abstention |
| 切分 | canonical `sha256(f"baton14f-fold-v1:{doc_id}")[:8] % 5`，未重新設計 |
| normalization | 只在 training fold 上 fit（mean/std），再 apply 到 held-out |
| 訓練資料 | 只有 `gold path ∈ top-10` 的 4,634 句可造 pair |
| optimizer | Adam，lr 1e-3，weight_decay 1e-4，60 epochs，batch 64 句 |
| 隨機種子 | 20260818（torch 與 shuffle 皆固定）|

**本棒只有一個模型、一組 feature、一個 objective、一個 protocol。
結果不佳後未回頭修改任何一項，也未開 ⑭-S2。**

held-out 資料未被用於：看 label、看 gold path、做 normalization、
選 architecture、選 threshold。

---

## 10. 分母對帳（provenance）

`path_score_dump` 記到的 walk 錯字是 **3,205**，D2 是 **3,192**，差 **13**。

已查清：**只有一句**（sid 1517）——它的 walk 輸出字數與金標不等
（節點跨度合計對不上），⑭-M / ⑭-P 依慣例整句排除，
本棒的 dump 則以 `e = 金標長度 = 13` 計入。

* 這一句的所有 10 條路徑都是長度不符，`n_err` 全部 13 →
  reranker 換誰都一樣，**對 rescue / damage / net 的貢獻恆為 0**。
* 因此主結果 **+53 不受影響**；但分母寫成 3,205 而非 3,192，
  兩者 `NOT COMPARABLE`，此處明確標出。

---

## 11. Failure-mode 分析

### Q：reranker 是不是只學到「某些方向比較容易錯」？

**沒有。** 這是本棒最重要的正面結果。

| 切分 | rescue | damage | net |
|---|---|---|---|
| document-held-out（主結果）| 239 | 186 | **+53** |
| **direction-held-out**（診斷）| 251 | 217 | **+34** |

方向完全沒見過時仍然是正的。對照 ⑭-N：節點層在 direction-held-out 下
條件 AUC **0.459（低於隨機）**，逐方向崩到 0.05–0.18。
**路徑層與節點層在這一點上本質不同，本棒予以確認。**

### ⚠️ 這個診斷第一版是壞的，記錄在此

第一版把 fold 直接用「該句第一個錯字的方向」雜湊指派 ——
但**解對的句子沒有方向**，全部落進同一個 fold；
該 fold 被held out 時，訓練集幾乎看不到「不要弄壞正確句」的例子，
damage 爆到 2,044、net **−1,715**。

那不是方向崩潰，是切分設計錯誤。修正方式：
**只對解錯的句子做 direction-held-out，解對的句子仍照 document 雜湊分散**。
修正後 +34。**壞掉的版本與修正版都寫在這裡，不只報好看的那個。**

### 逐方向

n≥10 的方向共 24 個，其中 **4 個淨為負**（最差 `什→甚` −11、`作→座` −1）。
942 個 n<10 的方向標 `INSUFFICIENT POWER`（保留未刪），合計 net +102。

---

## 12. 為什麼 ranking 變好而 net 變差

top-1 +0.8pp、MRR +0.006、pairwise +0.003 —— 排序確實變好，但：

* reranker 改變決策的句子比權重掃描多，**兩側都放大**：
  rescue 239（+62）、damage 186（+78）。
* precision 從 0.621 掉到 0.562 → **每救 2 個要壞 1.6 個**，比 baseline 差。
* 原因與 ⑭-R 量到的結構一致：解對側 margin 中位 +1.923、
  解錯側 deficit 中位 +0.734，兩側**重疊 16.0%**。
  任何把 gold 往上推的機制都會同時推高那些「本來勉強贏著」的錯誤路徑。
  **learned scorer 沒有繞過這個結構，只是更用力地推。**

---

## 13. Oracle ceiling 檢查

| 量 | 值 |
|---|---|
| ⑭-P 可達 top-10 single-path oracle | **1,198 字（37.5% of D2）** `THEORETICAL UPPER BOUND` |
| ⑭-R 權重 counterfactual | +69（5.8% of ceiling）|
| **⑭-S learned reranker** | **+53（4.4% of ceiling）** |

**沒有超過 ceiling**，無需觸發 provenance audit。
兩種方法都只兌現了可達空間的 **4–6%**。

---

## 14. GO / HOLD / NO-GO

事前 gate（§21，未修改）：

| GO 的六個條件 | 實測 | 通過？ |
|---|---|---|
| cross-fitted net > +69 | **+53** | ❌ |
| rescue 增加 | 239 > 177 | ✅ |
| damage 沒有以相同幅度增加 | 186 vs 108（**增加更多**）| ❌ |
| document-cluster 95% CI 支持 improvement | [+3, +99]，涵蓋大量 < 69 的值 | ❌（對 baseline 而言）|
| 沒有 held-out direction collapse | +34，無崩潰 | ✅ |
| 沒有 leakage | feature audit 全綠 | ✅ |

NO-GO 的觸發條件「net ≤ +69」**直接命中**。

**→ 🔴 NO-GO。**

門檻未修改；未因結果不佳而改 loss / architecture / feature / threshold /
fold / candidate set 後重跑；未自行開 ⑭-S2。

---

## 15. 最後一句話的回答

> 「在固定 top-10 candidate set 下，learned path reranker 是否能突破現有
> component-weight counterfactual 的 +69 字上限，並以可泛化、低誤傷的方式
> 產生額外淨收益？」

**NO-GO。**

* net **+53** < baseline **+69**；95% CI **[+3, +99]**。
* 可泛化：**是**（direction-held-out +34，無 ⑭-N 式崩潰）。
* 低誤傷：**否**（damage 186 vs 108，precision 0.562 vs 0.621）。

**泛化性過關，誤傷控制不過關，淨值沒有突破。**

---

## 16. Recommendation

* 「在固定 top-10 上重新排序」這個方向，兩種實作（權重掃描、learned MLP）
  都落在 **+50 ～ +80 字**（+0.07 ～ +0.11pp 字級正確率），
  只兌現可達 ceiling 的 4–6%。**這個問題形式已經量到底了。**
* 若日後仍要動 path scoring，證據指向的不是「更好的重排器」，
  而是**改變候選集的產生方式或語言模型本身** ——
  因為 43.1% of D2 的正解連 top-200 都沒有（⑭-P），
  而剩下那 37.5% 的可達空間，重排在兩種實作下都只拿到 4–6%。
  **那已經超出「reranking capability」的範圍，需要另立研究線。**
* 本棒不建議、也不啟動任何後續實驗。

---

## 17. Unknowns

1. 更大的模型／更豐富的特徵（候選字身分、局部 context）能否改變結論 —— `UNKNOWN`。
   本棒依規定只跑一組設定，**不得**為此重跑。
2. 兩側 margin 重疊（16.0%）是不是**資訊上的**上限，還是特定分數族的性質 —— `UNKNOWN`。
3. 43.1% of D2 的正解不在 top-200，成因 `UNKNOWN`（⑭-P 未解）。
4. 真實打字流量：完全沒有資料。全部證據為 PTT `CORPUS-LEVEL EVIDENCE`。
5. 本 dump 不含 `ParticleRuleDisambiguator`，與出貨路徑 `NOT COMPARABLE`。

---

## 18. Production integrity

| 項目 | 狀態 |
|---|---|
| production C++ / scoring / `walk()` / `walkNBest()` / 候選生成 | **未動** |
| ν / λ / τ / `path-char-lstm.bin` / `ParticleRuleDisambiguator` | **未動** |
| 候選集 | 完全固定為 production 已產生的 top-10 |
| 匯出可上線權重 | **沒有** |
| merge / enable / 接 app / 正式 test | **全部未做** |

---

## 19. 資料出處

| 項目 | 出處 |
|---|---|
| 全語料 5,976 句 × top-10 路徑分數 | `bin/path_score_dump`（⑭-Q 新增、⑭-R 加 `all=1`）|
| 訓練與 cross-fitted 評估 | `Source/Engine/eval/train_path_reranker.py`（**本棒新增**）|
| 逐方向與 direction-held-out 診斷 | `Source/Engine/eval/audit_path_reranker_directions.py`（**本棒新增**）|
| baseline +69（cross-fitted counterfactual）| `analysis/path-score-symmetric-damage.md`（⑭-R）|
| 可達 top-10 oracle 37.5% of D2 = 1,198 字 | `analysis/full-corpus-nbest-oracle.md`（⑭-P）|
| 句內 pairwise 0.824、逐方向不崩潰 | `analysis/path-score-discriminability.md`（⑭-Q）|
| 節點層 direction collapse（條件 AUC 0.459）| `analysis/node-expert-generalization.md`（⑭-N）|
| D2 = 3,192 | `analysis/full-error-budget.md`（⑭-O）|
