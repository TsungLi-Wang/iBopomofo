# n-gram + RNN 混合解碼（主線設計）

**最後更新：2026-07-09T17:05:00+08:00**  
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

**結論（粗分）：** 殘餘不全是「同路徑換 unigram 就好」。見下一節 **Oracle 上界**——同路徑天花板只有約三成 miss；其餘必須動 path／切詞。

## 2.1 Oracle 上界分析（2026-07-09，真跑）

### 定義（嚴格）

| 詞 | 意思 |
|----|------|
| 選錯 | bigram walk（λ=0.75）整句 top-1 ≠ expected（221 句） |
| 同路徑 | walk 產出的 **path 節點固定**（切詞／readings 不變） |
| 正解已在 unigram 候選內 | 僅在各 node 的 `unigrams()` 裡改選，能否 **拼出整句 expected** |
| 排名 | gold unigram 在該 node 分數排序中的 1-based 名次；句級取「需改選 node」的 **最差** 名次 |

這是 `WalkResult::reselectUnigramValue`／單點 RNN reselect 的理論天花板——**不是** lattice 全域 oracle（允許換 path）。

### 重跑指令

```bash
cd Source/Engine/eval/benchmarks
clang++ -std=c++17 -O2 -I../.. -I../../gramambular2 \
  same_path_oracle.cpp ../../gramambular2/reading_grid.cpp \
  ../../CorpusBigramContextModel.cpp ../../ParselessLM.cpp \
  ../../ParselessPhraseDB.cpp ../../MemoryMappedFile.cpp \
  -o /tmp/same_path_oracle
/tmp/same_path_oracle tw-sentences.tsv ../../../Data/data.txt \
  ../../../Data/word-bigrams.tsv 0.75
```

工具：`Source/Engine/eval/benchmarks/same_path_oracle.cpp`（獨立 harness，**不**進 app target Sources；Xcode 僅 file reference 於 Engine/eval/benchmarks）。

### 結果（cold，出貨 word-bigrams.tsv，λ=0.75）

北極星確認：bigram **174/395** 正確 → **221** miss。

| 項目 | 句數 | 比例 |
|------|-----:|-----:|
| 總錯誤句數 | **221** | 100% |
| 正解已在同路徑 unigram 候選內（整句可救） | **66** | **29.9%** |
| 正解不在同路徑 unigram 候選內（reselect 救不回） | **155** | **70.1%** |
| 其中 insert-failed | 9 | 4.1% of 221 |

**完美 same-path reselect 上限：** 174+66 = **240/395（60.8%）**。

### 分層（僅 in-oracle 66 句）

| 分層（最差 gold 名次） | 句數 |
|------------------------|-----:|
| 正解排第 **1** 位 | **3** |
| 正解排第 **2～3** 位 | **43** |
| 正解排第 **4** 位之後 | **20** |

### 代表性例子

1. **可救 · rank 2** — expected「請慢慢**地**走」／ got「請慢慢**的**走」  
   node `慢慢的|慢慢地`：慢慢的(-5.20) | 慢慢地(-5.52) → gold **第 2**。  
2. **可救 · rank 3** — expected「**她**是一位好老師」／ got「**他**是…」  
   node `他是|它是|她是` → gold「她是」**第 3**。  
3. **可救 · rank 1** — expected「…重開**機**」／ got「…重開**基**」  
   top 已是「機」，bigram 選成「基」→ reselect 回 top 即可。  
4. **可救 · rank 1** — expected「…很**清**」／ got「…很**輕**」  
   top5：清(-3.39) | 輕(-3.65) | …  
5. **可救 · rank 6** — expected「這**枝**筆…」／ got「這**之**比…」  
   「枝」在 33 候選深層；另「筆」rank 2。  
6. **救不回** — expected「我想**再喝**…」／ got「我想**在吃**…」  
   node 僅 unigram「我想在」(ug=1)，同路徑無「我想再」。  
7. **insert-failed** — expected「他在辦公室上電腦」→ readings 進不了 lattice。

### 對主線的含義

1. **只把 reselect 做到極致不夠**——天花板約救 30% miss。  
2. **可救的 66 句**多在 rank 2–3；RNN margin 要能看進 top-k，不能只盯 top-1。  
3. **155 句**要 **n-best／換 path／補詞**——下一刀應把 RNN 推進到 **path 層級選路**，不是停在單點 reselect。

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

1. ~~同路徑 oracle 上界~~ → **已完成**（§2.1：66/221 可救，155 需 path 層）。  
2. **n-best + RNN 選路**（優先）：n-gram 產 K 條完整路徑，`S_ngram + ν·S_rnn` 選路——針對 155 的主力。  
3. **RNN 單點仍走 `reselect`**：deferred／候選窗寫入 `reselectUnigramValue`（服務 in-oracle 66 句）。  
4. 可選：把 155 再拆「切詞鎖死／缺孿生／insert-failed」細分類。  
5. 殘餘仍 miss 再談 trigram／更大模型——**不是**回頭主攻表瘦身。

## 6. 驗收鐵則

- 北極星 cold bigram 數字不得無故倒退（個人化 cold 空）。  
- 混合相關改動：`chosenValueAt` 讀路徑；給實機句前 harness。  
- 三項狀態分列：app build / 單元測試 / eval harness。
