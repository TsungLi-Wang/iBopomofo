# n-gram + RNN 混合解碼（主線設計）

**最後更新：2026-07-09T16:30:00+08:00**  
**目標方向：** Mozc 級 n-gram 解碼為底，再疊 RNN／神經路徑打分（文獻 n-gram+RNN 混合路線）。  
**不是主線：** 表瘦身、EM 重跑、新詞月更（可並行，但不是這條路的目的地）。

## 1. 現況底盤（n-gram 層，已出貨）

| 層 | 狀態 |
|----|------|
| Lattice + Viterbi / 精確 bigram DP | `ReadingGrid::walk()` + `ContextModel` |
| 詞 bigram（語料 PMI） | `CorpusBigramContextModel`，λ=0.75，預設開 |
| 個人 soft | `CompositeContextModel` + UOM，v2.3 |
| 路徑選字真相 | `WalkResult::selectedUnigramIndices` + `chosenValueAt` |
| 字元 n-gram 候選窗 | L1 `AICandidateNGramScorer`（側線，非解碼主軸） |
| 既有神經（貼丁形態） | 候選窗 neural + deferred soft override，**實驗預設關** |

北極星（cold，出貨表）：walk OFF **164/395**，bigram ON **174/395**。

## 2. 殘餘錯誤（bigram 之後，真跑）

指令：

```bash
cd Source/Engine/eval/benchmarks
./build-and-run.sh tw-sentences.tsv                    # baseline misses
./build-and-run.sh tw-sentences.tsv ../../../Data/word-bigrams.tsv 0.75
```

| 集合 | 句數 |
|------|------|
| baseline miss | 231 |
| bigram miss | 221 |
| bigram 修好 | 21 |
| bigram 弄壞 | 11 |
| 兩邊都 miss | 210 |

bigram miss 粗分類（221）：

| 型 | 約 | RNN／混合能否碰 |
|----|---:|----------------|
| 同長字元替換 | 206 | **主戰場**：同音／近義、路徑上換 unigram |
| 的／得／地 族 | 14 | 既有 deferred 字集 + 混合路徑 |
| 在／再 族 | 13 | 混淆表優先；神經刻意排除 ㄗㄞˋ |
| insert-failed | 9 | 詞庫／lattice 建不起 → **不是 RNN** |
| 長短不一致 | 6 | 切詞／缺詞 → 多半不是單點 RNN |

**結論：** 殘餘以「lattice 上有候選、n-gram 選錯」為主 → 適合 **n-best／同路徑 unigram 的 RNN 重打分**，不是先擴詞庫當主線。

## 3. 混合架構（目標形態）

打分函數（概念）：

```
S(path) = S_unigram + λ·S_bigram + μ·S_user + ν·S_rnn(path 或局部替代)
```

約束（與 bigram walk 同一哲學）：

1. **不生成新字**——只在 node 既有 unigram 裡改選。  
2. **選擇活在 `WalkResult`**——`selectedUnigramIndices`／`reselectUnigramValue`，不靠長期污染 UOM 的 hard override。  
3. **n-gram 先產路徑**，RNN 在可負擔時機重評（右文≥2、停頓、句末）——因果 LM 沒有右文時與 local 等價（見既有 deferred 分析）。  
4. **使用者手選永遠優先**；`chosenValueAt`：override > DP 索引 > top unigram。

### 與「外面貼丁」的關係

| 舊（過渡） | 新（混合主線） |
|------------|----------------|
| deferred：`selectOverrideUnigram` 改 node | 同效結果改寫 **`reselectUnigramValue` + indices** |
| 候選窗 neural：排順序 | 可保留；解碼正解仍以 walk 路徑為準 |
| 混淆表 ㄗㄞˋ | 仍分工，直到混合在 ㄗㄞˋ 集追平 |

## 4. 已開工（本棒第一刀）

1. **`WalkResult::reselectUnigramValue`** — 純路徑改選 API（混合寫入點）。  
2. **`chosenValueAt` 優先序** — post-walk override 蓋過 DP 索引（修 contextual walk 開時神經翻字可能上不了屏）。  
3. **`KeyHandler` neural apply** — soft override 成功後同步 `reselectUnigramValue`。  
4. **gtest** — post-walk reselect / post-walk soft override 兩條回歸。

## 5. 下一刀（依序）

1. **同路徑 oracle 上界**：221 miss 裡有多少「正確字已在該 node unigram 內」→ 定 ν 與觸發策略的天花板。  
2. **RNN 路徑打分接 `reselect`**：deferred 決策結果只走 reselect（可逐步拿掉對 display 的 override 依賴）。  
3. **n-best / 局部 beam**：n-gram 產 K 條完整路徑，RNN 打 `S_ngram + ν·S_rnn` 選路（對齊文獻 path rescoring）。  
4. 殘餘仍 miss 再談 trigram／更大模型——**不是**回頭主攻表瘦身。

## 6. 驗收鐵則

- 北極星 cold bigram 數字不得無故倒退（個人化 cold 空）。  
- 混合相關改動：`chosenValueAt` 讀路徑；給實機句前 harness。  
- 三項狀態分列：app build / 單元測試 / eval harness。
