# 新北極星評分機（newstar_homophone_eval）

字級同音消歧、按混淆對頻率加權、train / held-out 分報。  

- **tw538 已作廢**（歷史句級尺）；本 harness 是難題／同音消歧尺。  
- 出貨 gate 是 repo 根目錄 `scripts/ship-gate.sh`（**真實語料**不得淨傷害），**不是**本檔的 EX1166 總分。  
- 預設 scorer 參數：`shipping`、λ=0.75、ν=0.75；**UOM 關閉**。  
- 出貨權重請用 **`Source/Data/path-char-lstm.bin`（v2d int8）**；`eval/models/path-char-lstm-spoken-v2c.bin` 是舊 float 基準、`…-v2d.bin` 是 float 微調檔，**量「現役產品」時以 Data 下 int8 為準**。

## 與最終出題管線的對齊

| 步驟 | 內容 |
|------|------|
| 1 | AI 只生**純句子**（連續漢字，無標點、無空格） |
| 2 | 小麥線上工具加注音 → `full_reading`（**空白分隔**音節） |
| 3 | Python 轉 JSONL（雙向出題：如一半「在」、一半「再」，`pair_id` 同為 `在/再`） |
| 4 | 本 harness 跑分 |

### JSONL 契約（必填欄位）

| 欄位 | 說明 |
|------|------|
| `sentence_id` | 同句多目標共用 |
| `sentence` | 連續漢字（無標點） |
| `target_index` | 目標字 **字級** 0-based 位置 |
| `target_char` | 目標字（單一字元） |
| `wrong_chars` | 干擾字陣列（2-way 一個、3-way 兩個…） |
| `reading` | 目標與干擾字共同讀音 |
| `pair_id` | 混淆對 ID（雙向合併計分，例 `在/再`） |
| `n_way` | `1 + len(wrong_chars)` |
| `weight` | 該對頻率權重（進 headline 加權） |
| `tier` | `single` \| `multi` |
| `split` | `train` \| `heldout`（**評分機不自動切分**，全看此欄） |
| `domain` | 可選 |
| `full_reading` | 整句注音；**空白或 `-` 分隔**皆可（內部正規成 `-`） |
| `source` | 可選 |

健檢失敗的題會 `REJECT …` 並列出，**不進分數**。

## 雙尺與 FLOOR（棒① · 2026-08-11）

| 工具 | 用途 |
|------|------|
| `main_scale_dedup.py` | 對 FP_train（PTT spoken + v2d 在再訓句）exact+8-gram 去重 → `~/laowang-data/main-scale/MAIN_SCALE.jsonl` |
| `floor_pass.py` | 基線 dump vs 改動 dump → `b/c/n/p/α/FLOOR_PASS`（單尾；**不要**用 `compare_dumps.py` 當 FLOOR） |
| `run_dual_scale_baseline.sh` | 一鍵 MAIN + EX1166 shipping 基準 |

出貨配置：`path-char-lstm.bin` + `shipping 0.75 0.75` + `particle-rules.tsv`；UOM off。  
EX1166 **只參考**；宣稱進步必須主尺 + 後續 `FLOOR_PASS`。

## 一行跑法（可直接複製；絕對路徑）

```bash
# 若 /tmp/newstar_homophone_eval 不在，先建置（見下節）
# 現役出貨權重 = Source/Data/path-char-lstm.bin（v2d int8）
/tmp/newstar_homophone_eval \
  /Users/johnny.w_macmini/Documents/i注音-語料/EX1166-題庫/EX1166-全部.jsonl \
  /Users/johnny.w_macmini/iBopomofo/Source/Data/data.txt \
  /Users/johnny.w_macmini/iBopomofo/Source/Data/word-bigrams.tsv \
  /Users/johnny.w_macmini/iBopomofo/Source/Data/path-char-lstm.bin \
  shipping 0.75 0.75
```

換題庫只改第一個參數。日常體感另跑：

- `…/自然驗證集-真實語料.jsonl`
- `…/X驗證集-真實語料.jsonl`

### 對照實驗（改引擎必跑）

第 8 個參數是 `confusion-alphas.tsv`（不給＝不套用；**現役檔無生效條目**），  
第 9 個是 dump.tsv，第 10 個可選 `particle-rules.tsv`。

```bash
EX=/Users/johnny.w_macmini/Documents/i注音-語料/EX1166-題庫/EX1166-全部.jsonl
R=/Users/johnny.w_macmini/iBopomofo
ARGS="$R/Source/Data/data.txt $R/Source/Data/word-bigrams.tsv \
      $R/Source/Data/path-char-lstm.bin shipping 0.75 0.75"

# 對照組：機制關閉。**先確認這個數字跟你改程式之前一模一樣**，再往下走。
/tmp/newstar_homophone_eval $EX $ARGS "" dump-off.tsv

# 實驗組（例：只開 particle 規則；alphas 目前應等同關閉）
/tmp/newstar_homophone_eval $EX $ARGS \
  $R/Source/Data/confusion-alphas.tsv dump-on.tsv \
  $R/Source/Data/particle-rules.tsv
```

然後拿兩份 dump 做 **McNemar 配對檢定**（改對幾題 vs 改錯幾題）。

⚠️ **只看總分會騙人**：「淨 +41 題」可以是「84 對／43 錯」，也可以是「300 對／259 錯」，
兩者的意義完全不同。淨值一樣，可信度差很多。

## 建置（執行檔不見時）

```bash
cd /Users/johnny.w_macmini/iBopomofo/Source/Engine/eval/benchmarks
ENGINE=../..
clang++ -std=c++17 -O2 \
  -I"$ENGINE" -I"$ENGINE/gramambular2" \
  newstar_homophone_eval.cpp \
  "$ENGINE/gramambular2/reading_grid.cpp" \
  "$ENGINE/CorpusBigramContextModel.cpp" \
  "$ENGINE/NeuralLMPathScorer.cpp" \
  "$ENGINE/ParselessLM.cpp" \
  "$ENGINE/ParselessPhraseDB.cpp" \
  "$ENGINE/MemoryMappedFile.cpp" \
  -framework Accelerate \
  -o /tmp/newstar_homophone_eval
```

內建 sample 自證：

```bash
/tmp/newstar_homophone_eval \
  /Users/johnny.w_macmini/iBopomofo/Source/Engine/eval/benchmarks/newstar_sample.jsonl \
  /Users/johnny.w_macmini/iBopomofo/Source/Data/data.txt \
  /Users/johnny.w_macmini/iBopomofo/Source/Data/word-bigrams.tsv \
  /Users/johnny.w_macmini/iBopomofo/Source/Data/path-char-lstm.bin \
  shipping 0.75 0.75
```

## 模式

| mode | 行為 |
|------|------|
| `shipping`（預設） | contextual λ + 路徑神經重排 ν（出貨權重＝v2d int8）；**UOM 關閉** |
| `walk` | 僅 walk + contextual bigram，無神經重排 |

## 現況規格（重要）

| 項目 | 現況 |
|------|------|
| **held-out** | **不自動切分**；完全依 JSONL 的 `split` 欄（`train` / `heldout`）分組報表 |
| **詞級目標** | **目前不支援**。只比 `utf8Chars(output)[target_index] == target_char`（單一字元）。若要詞級：需擴欄位（如 `target_span`/`target_len`）並改比對為輸出連續子串等於 `target_char`（多字） |
| **逐對表排序** | **worst-first**（依該對 raw_acc 由低到高；同分依 `pair_id`） |

## 輸出重點

- `ITEMS_LOADED` / `REJECTED` + 每筆 `REJECT line=… reason=…`
- 分組：`single|train` / `single|heldout` / `multi|train` / `multi|heldout`
- headline：加權字級正確率 + 未加權
- 逐對表：pair_id | n_way | items | correct | raw_acc | weight | w_contrib
- multi 另印整句所有 target 全對比例
- 收尾行：`NEWSTAR single train weighted=… heldout=…`

---

## 文法規則：從歸納到上線的流程（2026-08-10 建立）

引擎的 `ParticleRuleDisambiguator` 已改成**通用規則引擎**，讀規則表而不是寫死一組。
規則表格式與 `try_rules.py` 完全相同，所以流程是：

```
induce_rules.py（從 train 挖規則）
      ↓
try_rules.py（幾秒鐘試跑，看救回幾題／改壞幾題）
      ↓  數字夠好才往下
newstar_homophone_eval ... [alphas] [dump] [規則表]   ← 真引擎對照實驗
      ↓
放進 Source/Data/，由 KeyHandler 載入
```

**重點是中間那步幾秒鐘就跑完**，不必為了試規則重編引擎。編譯＋跑 5,646 題要好幾分鐘，
規則要迭代十幾輪，這個差別決定這條路走不走得下去。

### 規則表格式

```
GROUP    前錢                     這組叫什麼（對應 jsonl 的 pair_id）
READING  ㄑㄧㄢˊ
LIST     謂語開頭   別             清單成員，一行一個
RULE     時間狀語   錢   前   R1=謂語開頭
         ↑規則名   ↑從  ↑改成 ↑條件（分號分隔，全部成立才出手）
```

條件：`L1/L2/R1/R2`（左右第 1、2 個字）、`LW2/RW2`（左右兩字合成的詞）、
`L1T/TR1`（含目標字，**只能當否定護欄**）、`END/NOTEND/START/NOTSTART`、
前綴 `!` 表否定、特殊清單 `@DICT` 查引擎詞庫。

⚠️ **正面規則的條件不可以包含目標字本身**（`L1T`/`TR1`）。規則是拿「引擎選出來的字」
比對的，引擎選錯時那個位置是錯字，這種條件永遠對不上，規則等於死的。

### 兩條歸納路線，實測互補

| 路線 | 做法 | 強項 | 弱項 |
|---|---|---|---|
| `induce_rules.py` | 掃 train 算支持度與純度 | 數得出來，擋得掉「只對一句」的規則 | 看不到語法結構 |
| 派 grok 讀例句 | 語法分析 | 說得出理由，抓得到結構性規律 | **會背題**，必須用它沒看過的資料驗 |

2026-08-10 實測（前錢／吧八巴封存集）：兩邊出手的題目重疊不到一半，
合併能再多救幾題，但誤判會疊加、出手準確率掉到 80%，低於「寧可少改不要改錯」的門檻。

### 派工給外部 AI 的鐵則

**只給 train 的例句，封存集一題都不能給。** 第一輪混著給，結果它交回來的規則
在看過的句子上準確率 96%、沒看過的只有 21% —— 整套是背例句。
收工時務必拆開「看過／沒看過」分開報，只看總分絕對看不出來。

---

## 讀過的文獻與採用結果

### 陳勇志、吳世弘等〈中文混淆字集應用於別字偵錯模板自動產生〉（2009，朝陽科大＋資策會）

那篇做的是**作文批改**（找出已寫下的錯別字），我們做的是**打字當下選字**，
但底層問題同構：一個位置有多個同音候選，要決定選哪個。2026-08-10 逐項評估如下。

| 那篇的方法 | 我們採用了嗎 | 為什麼 |
|---|---|---|
| **根號檢定**取代卡方 | **實作了，但預設不用** | 見下方 |
| **斷詞過濾跨詞邊界的假搭配** | **量過，不採用** | 見下方 |
| 同部首（同形字）混淆集 | **不適用** | 我們是注音輸入法，候選字被讀音鎖死，字形相似不會進候選 |
| 同音字混淆集自動產生 | **不需要** | 注音輸入法的「混淆集」就是同讀音底下的候選，引擎本來就有 |
| 通用詞造成的誤判（垃圾桶／垃圾筒） | **已知風險，未處理** | 我們的 `作/做` 在台灣有真實用法分歧，需要例外清單 |
| 統計：學生錯別字 79.88% 是同音字 | 佐證 | 支持我們把火力全放在同音字 |

#### 根號檢定：洞見對，公式不能照抄

那篇原本用卡方收模板，發現卡方允許「錯誤用法的頻率隨正確用法線性成長」，
但真實語料裡錯誤用法永遠稀有，所以卡方放進大量雜訊。改成
`sqrt(正確次數) > 錯誤次數` 之後 Micro Precision 從 84.3% 升到 91.3%。

**在我們的尺度上它反而更鬆。** 那篇的正確次數是語料庫詞頻（上萬），
`sqrt(100000)=316` 等於只容忍 0.3% 反例；我們的樣式在 4,125 題 train 裡
只出現 5~200 次，`sqrt(100)=10` 等於容忍 9% 反例。

實測（train，`induce_rules.py --criterion`）：

| 準則 | 淨賺 | 出手準確率 |
|---|---|---|
| 固定純度 90%（原本的做法） | +330 | **98.0%** |
| 根號檢定（那篇的公式） | +453 | 88.2% |
| Wilson 信賴區間下界 0.70 | +183 | 96.0% |

**但那篇的洞見是對的：門檻該隨樣本數變。** 只是在我們的規模要往反方向 ——
小樣本要更嚴（估不準），所以正確的做法是信賴區間下界而不是根號。
三個準則都留在 `induce_rules.py` 裡；語料規模長大之後根號檢定會變成對的選擇。

#### 斷詞過濾：那篇效果最大的一招，我們用不到

那篇單一改動效果最大的就是這個（Micro Precision 91.3% → 95.5%）。它的例子：
用「擁有」抓反面用語會收進「一個人可**以有**很多快樂」的「以有」，
但那個「以」屬於「可以」—— 跨詞邊界的假搭配。

我們**免費就有斷詞**（walk 的節點邊界，已加進評分機逐題輸出的 `segments` 欄）。
但實測它分不出好壞：

|  | 救回的題目 | 改壞的題目 |
|---|---|---|
| 左鄰字跨詞邊界 | 78% | 87% |
| 右鄰字跨詞邊界 | 93% | 100% |

要求「必須同節點」會殺掉 78~93% 的正確出手，只為擋掉那些誤判，淨虧。

**原因**：那篇抓的模板本身就在一個詞裡面，所以跨邊界＝假搭配。
我們的題庫**刻意排除了「詞庫一刀切」的送分題**，目標字本來就幾乎不在詞裡面 ——
這一招要防的情況，被我們的出題設計先排除掉了。
（真實打字時那種情況很常見，但那時引擎的詞圖本來就處理掉了。）

`segments` 欄留著當診斷用。
