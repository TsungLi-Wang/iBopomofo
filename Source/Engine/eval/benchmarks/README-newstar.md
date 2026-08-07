# 新北極星評分機（newstar_homophone_eval）

字級同音消歧、按混淆對頻率加權、train / held-out 分報。  
與 **tw538 句級北極星並存**，不取代。  
引擎零改；預設出貨 scorer（λ=0.75、ν=0.75、v2c）；**UOM 關閉**。

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

## 一行跑法（可直接複製；絕對路徑）

```bash
# 若 /tmp/newstar_homophone_eval 不在，先建置（見下節）
/tmp/newstar_homophone_eval \
  /Users/johnny.w_macmini/Downloads/zai30.jsonl \
  /Users/johnny.w_macmini/iBopomofo/Source/Data/data.txt \
  /Users/johnny.w_macmini/iBopomofo/Source/Data/word-bigrams.tsv \
  /Users/johnny.w_macmini/iBopomofo/Source/Engine/eval/models/path-char-lstm-spoken-v2c.bin \
  shipping 0.75 0.75
```

換真題庫時只改第一個參數路徑。

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
  /Users/johnny.w_macmini/iBopomofo/Source/Engine/eval/models/path-char-lstm-spoken-v2c.bin \
  shipping 0.75 0.75
```

## 模式

| mode | 行為 |
|------|------|
| `shipping`（預設） | contextual λ + v2c path rerank ν；**UOM 關閉** |
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
