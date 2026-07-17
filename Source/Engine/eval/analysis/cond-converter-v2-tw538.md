# CondConverter v2 — conditional conversion reranker on tw538

**Question the baton asked:** with the data prior fixed (77.7M-char corpus vs
the old 12.6M), can the *conditional* form P(han | reading, context) — reading
as a hard conditioning input, zenz-style — beat the general-LM ceiling of 387?

**Answer: yes, and it is complementary to the general LM.**
Best fusion `walk + 0.5·v2c_lstm + 0.25·cond` → **397/537 (73.9%), +10 over
v2c's 387.**

## Model

- Arch: `CondConverter` — char-emb + reading-syllable-emb, ctx-LSTM + reading-
  LSTM, fused → decoder-LSTM init state, teacher-forced char decode. Reading is
  encoded and fused into the decoder state (hard conditioning), **not** a soft
  additive feature.
- Size: emb256 / hidden512 / layers1 → **11,681,373 params** (in the 8–12M
  target band; v2c char-LSTM is 9.73M).
- Data: **all 42,938,923 train pairs** (+635,856 hash-holdout val) from the
  rebuilt 77.7M-char corpus (conversion_pairs_v2.tsv). Streaming trainer
  (16GB-safe). `best_val_ppl ≈ 1.25`.
- **Training reached only epoch 1** (a post-epoch-1 meta-write bug crashed the
  run before epoch 2; bug fixed in d97994f). The epoch-1 loss had already
  plateaued (~0.06 from batch 8000; val_ppl 1.25). A clean 2-epoch retrain is
  an available follow-up (expected marginal, given the plateau).
- Weights: `models/cond-converter-v2.bin` (SHA256 in `.sha256`).

## tw538 results (537 sentences, N-best N=10, λ=0.75)

Control (regression check — reproduces the known baselines exactly):

| config | correct |
|---|---|
| walk ON (λ=0.75) | 333 |
| **v2c LSTM only, ν=0.75** | **387** ✓ reproduced |

Cond-only (walk + ν·cond):

| ν | 0.25 | 0.5 | 0.75 | 1.0 |
|---|---|---|---|---|
| correct | 366 | 380 | **383** | 378 |

A 1-epoch conditional model alone reaches 383 — within 4 of the 9.73M char-LSTM.

Three-way mix (walk + ν_lstm·v2c + κ_cond·cond):

| v2c ν \ cond κ | 0.25 | 0.5 | 1.0 |
|---|---|---|---|
| **0.5** | **397** ⭐ | 393 | 390 |
| 0.75 | 396 | 394 | 384 |

**Best: walk + 0.5·v2c + 0.25·cond → 397/537.** pool mean_ms ≈ 2200 (research
config: both scorers run per candidate; latency debt, not a shipping config).

## A-class attribution (best mix vs v2c)

single_char_swap = expected & chosen same length, differ in exactly 1 char;
A-class = gold is inside the N-best pool (rerankable), B-class = pool-miss.

| config | total wrong | A-class (in-pool) | B-class (pool-miss) | A single_char_swap |
|---|---|---|---|---|
| v2c (387) | 150 | 83 | 67 | 69 |
| **mix (397)** | 140 | **73** | 67 | **65** |

- **All +10 gains are A-class** (83→73). Cond is a pool reranker → cannot touch
  B-class (67, unchanged either way). B-class remains the constraint-research
  (Zenzai) target for a future baton.
- single_char_swap 69→65: the conditional model chips into the exact
  single-char homophone errors the general LM could not (的/得, 他/它, 股/古,
  容/熔, 版/板 …) — the baton's thesis, confirmed directionally (modest −4).

## Reproduce

```bash
ENGINE=Source/Engine
clang++ -std=c++17 -O2 -I"$ENGINE" -I"$ENGINE/gramambular2" \
  $ENGINE/eval/benchmarks/tw538_cond_rerank.cpp \
  $ENGINE/CondPathScorer.cpp $ENGINE/CondConverterScorer.cpp \
  $ENGINE/gramambular2/reading_grid.cpp $ENGINE/CorpusBigramContextModel.cpp \
  $ENGINE/NeuralLMPathScorer.cpp $ENGINE/ParselessLM.cpp \
  $ENGINE/ParselessPhraseDB.cpp $ENGINE/MemoryMappedFile.cpp -o /tmp/tw538_cond_rerank

cd $ENGINE/eval/benchmarks
/tmp/tw538_cond_rerank tw538-northstar.tsv ../../../Data/data.txt \
  ../../../Data/word-bigrams.tsv 0.75 \
  ../models/cond-converter-v2.bin ../models/path-char-lstm-spoken-v2c.bin
# expect: LSTM_ONLY NU 0.75 → 387 ; MIX nu_lstm=0.5 kappa_cond=0.25 → 397
```

Training (corpus + pairs rebuild in cond-corpus-v2-rebuild-drift.json):

```bash
python3 $ENGINE/eval/train_cond_converter.py \
  --pairs ~/laowang-data/conversion_pairs_v2.tsv --stream --num-workers 4 \
  --out models/cond-converter-v2.bin \
  --emb 256 --hidden 512 --layers 1 --epochs 2 --batch 1024
```
