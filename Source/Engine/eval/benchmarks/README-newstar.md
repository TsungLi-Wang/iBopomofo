# 新北極星評分機（newstar_homophone_eval）

字級同音消歧、按混淆對頻率加權、train / held-out 分報。  
與 **tw538 句級北極星並存**，不取代。

## 建置與跑 sample

```bash
cd Source/Engine/eval/benchmarks
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

# 內建 sample（骨架自證）
/tmp/newstar_homophone_eval \
  newstar_sample.jsonl \
  ../../../Data/data.txt \
  ../../../Data/word-bigrams.tsv \
  ../models/path-char-lstm-spoken-v2c.bin \
  shipping 0.75 0.75
```

## 指到真題庫

```bash
/tmp/newstar_homophone_eval \
  /path/to/real_items.jsonl \
  ../../../Data/data.txt \
  ../../../Data/word-bigrams.tsv \
  ../models/path-char-lstm-spoken-v2c.bin
```

JSONL 契約見 `newstar_sample.jsonl` 與 baton 規格（`sentence_id` / `target_index` / `pair_id` / `weight` / `tier` / `split` / `full_reading` …）。

## 模式

| mode | 行為 |
|------|------|
| `shipping`（預設） | contextual λ + v2c path rerank ν（預設 0.75）；**UOM 關閉** |
| `walk` | 僅 walk + contextual bigram，無神經重排 |

## 輸出重點

- 髒題：`REJECT line=… reason=…`（排除、不靜默計分）
- 分組：`single|train` / `single|heldout` / `multi|train` / `multi|heldout`
- 逐對表 worst-first
- 收尾行：`NEWSTAR single train weighted=… heldout=…`
