# Taiwan Typing Benchmark (north-star metric)

Full-sentence top-1 character accuracy on clean Taiwan sentences: convert the
reading key sequence with the engine `walk()` and compare the whole string to
the expected text. This is the single objective judge for engine changes.

- **`tw538-northstar.tsv` (current north-star)**: `readings<TAB>expected_text`,
  **537** cases. Real PTT lifestyle-board article bodies (not Gossiping /
  C_Chat), mainland/Cantonese/jargon filtered, Johnny human-reviewed.
  Default for `build-and-run.sh`.
- `tw-sentences.tsv` (**archive only**): previous 395-case set. Kept for
  historical comparison; do not use as the default judge for new work.
- `tw_benchmark.cpp` / `build-and-run.sh`: compile against the real dictionary
  and print baseline accuracy. Results are read via `walk().chosenValueAt(i)`,
  the only correct way to read a walk that used a `ContextModel` (the DP records
  its choice in `selectedUnigramIndices` without mutating the nodes, so
  `valuesAsStrings()` / `node->value()` do not reflect it).

## Baseline (tw538)

```
./build-and-run.sh
# or explicitly:
./build-and-run.sh tw538-northstar.tsv ../../../Data/word-bigrams.tsv 0.75
```

Numbers are recorded in `CHANGELOG.md` / `AI_HANDOFF_PROMPT.md` after each
rebuild on this set. Historical 395 baselines (for archive):

```
# archive only
./build-and-run.sh tw-sentences.tsv
# Unigram-only walk (395): 41.5% (164/395); contextual λ=0.75: 44.1% (174/395).
```

## Reproduce spoken LSTM n-best

### Current best: **387/537** (ν=0.75, N=10) — v2c

Weights (persistent under `../models/`):

| weight | arch | params | best on tw538 | mean_ms | SHA256 file |
|--------|------|--------|---------------|---------|-------------|
| `path-char-lstm-spoken-v2c.bin` (~37MB) | emb256/hid512 | 9,734,083 | **387 @ ν=0.75** | ~730 | `*.sha256` |
| `path-char-lstm-spoken-v2b.bin` (~15MB) | emb128/hid256 | 3,953,475 | 374 @ ν=0.75 | ~226 | `*.sha256` |
| `path-char-lstm-spoken-v2a.bin` (~6.7MB) | emb64/hid128 | 1,751,299 | 362 @ ν=0.5 | ~81 | `*.sha256` |
| `path-char-lstm-spoken.bin` (~4.9MB) | emb64/hid128 | 1,272,852 | 356 @ ν=0.5 (v1) | ~61 | `*.sha256` |

Capacity slope: `../analysis/tw538-capacity-slope.md`.  
Transformer vs v2c (negative result): `../analysis/tw538-tf-vs-v2c.md`.

```bash
# from Source/Engine/eval/benchmarks
ENGINE=../..
clang++ -std=c++17 -O2 -I"$ENGINE" -I"$ENGINE/gramambular2" \
  nbest_path_rerank.cpp \
  "$ENGINE/gramambular2/reading_grid.cpp" \
  "$ENGINE/CorpusBigramContextModel.cpp" \
  "$ENGINE/NeuralLMPathScorer.cpp" \
  "$ENGINE/ParselessLM.cpp" \
  "$ENGINE/ParselessPhraseDB.cpp" \
  "$ENGINE/MemoryMappedFile.cpp" \
  -o /tmp/nbest_neural

# NEW BEST (v2c)
/tmp/nbest_neural tw538-northstar.tsv ../../../Data/data.txt \
  ../../../Data/word-bigrams.tsv 0.75 \
  ../models/path-char-lstm-spoken-v2c.bin
# expect: BEST_NU 0.75 correct 387/537 ; mean_ms≈730
# walk OFF 296 / walk ON 333 (SLICE1_*)

# v2b 374
/tmp/nbest_neural ... ../models/path-char-lstm-spoken-v2b.bin
# expect: BEST_NU 0.75 correct 374/537

# v1 baseline 356
/tmp/nbest_neural ... ../models/path-char-lstm-spoken.bin
# expect: BEST_NU 0.5 correct 356/537
```

ν right-side scan harness: `tw538_nu_right_scan.cpp` (pool once, many ν).

### Train spoken v2 weights (pollution-safe Gossiping ≥40M han)

```bash
# 1) Build corpus (Gossiping QA v2 + push replies; bans tw538 boards + C_Chat)
python3 ../build_spoken_corpus.py \
  --qa-csv /path/to/Gossiping-QA-Dataset-2_0.csv \
  --qa-txt /path/to/Gossiping-QA-Dataset.txt \
  --extra-txt /path/to/replies_pushes_only.txt \
  --out /tmp/ptt_spoken_train_v2.txt \
  --stats ../analysis/spoken-corpus-v2-stats.json
# pack short lines optional for training speed (same han count)

# 2) Train (requires PyTorch)
# (a) emb64/hid128  (b) emb128/hid256  (c) emb256/hid512
python3 ../train_char_lstm_lm.py \
  --corpus /tmp/ptt_spoken_train_v2_packed.txt \
  --out ../models/path-char-lstm-spoken-v2c.bin \
  --epochs 4 --emb 256 --hidden 512 --layers 2 \
  --batch 128 --seq-len 64 --stream --device mps
```

Note on `--stream`: each training line is encoded with `<s>…</s>` (BOS/EOS);
flat concat keeps those boundary tokens between segments (no bare cross-doc splice).

### Char-Transformer (experimental; **not** better than v2c on tw538)

```bash
# train (~8.8M params: 6L d256 h4 ffn1024 ctx128)
python3 ../train_char_transformer_lm.py \
  --corpus /tmp/ptt_spoken_train_v2_packed.txt \
  --out ../models/path-char-tf-spoken.bin \
  --epochs 4 --stream --device mps

# eval (auto-detects LWTFMR1 magic)
clang++ -std=c++17 -O2 -I"$ENGINE" -I"$ENGINE/gramambular2" \
  nbest_path_rerank_any.cpp NeuralTFPathScorer.cpp ...same engine objs... \
  -o /tmp/nbest_any
/tmp/nbest_any tw538-northstar.tsv ../../../Data/data.txt \
  ../../../Data/word-bigrams.tsv 0.75 ../models/path-char-tf-spoken.bin
# recorded: best positive ν 0.25 → 332/537 (worse than walk ON 333)
```

Compare: `../analysis/tw538-lstm-v2-compare.md`, `../analysis/tw538-capacity-slope.md`,
`../analysis/tw538-tf-vs-v2c.md`.

### CondConverter v2 (conditional reranker — **beats v2c via mix → 397/537**)

Conditional P(han | reading, context) with reading as a hard conditioning
input (zenz-style), **not** a general LM. Unlike the char-Transformer (general
LM, lost at 332), the conditional form is *complementary* to v2c: the 3-way
mix beats both.

| weight | arch | params | best on tw538 | SHA256 |
|---|---|---|---|---|
| `../models/cond-converter-v2.bin` (~47MB) | emb256/hid512/L1 | 11,681,373 | cond-only 383 @ ν0.75; **mix 397** | `bbddad36f3cf03cfd497626bde5124360a22bfc961a0d3e76ef13ab7118880c3` |

```bash
# eval: cond-only ν scan + v2c control + 3-way mix + A-class dump
clang++ -std=c++17 -O2 -I"$ENGINE" -I"$ENGINE/gramambular2" \
  tw538_cond_rerank.cpp "$ENGINE/CondPathScorer.cpp" "$ENGINE/CondConverterScorer.cpp" \
  "$ENGINE/gramambular2/reading_grid.cpp" "$ENGINE/CorpusBigramContextModel.cpp" \
  "$ENGINE/NeuralLMPathScorer.cpp" "$ENGINE/ParselessLM.cpp" \
  "$ENGINE/ParselessPhraseDB.cpp" "$ENGINE/MemoryMappedFile.cpp" -o /tmp/tw538_cond_rerank
/tmp/tw538_cond_rerank tw538-northstar.tsv ../../../Data/data.txt \
  ../../../Data/word-bigrams.tsv 0.75 \
  ../models/cond-converter-v2.bin ../models/path-char-lstm-spoken-v2c.bin
# expect: LSTM_ONLY NU 0.75 → 387 ; MIX nu_lstm=0.5 kappa_cond=0.25 → 397
```

Corpus + 42.9M conversion pairs rebuilt from public zake7749 corpus
(drift <1%): see `../analysis/cond-corpus-v2-rebuild-drift.json` (with SHA256
of the persistent ~/laowang-data assets). Full result table + A-class
attribution: `../analysis/cond-converter-v2-tw538.md`.

### CondProposer constrained search (B-class path_locked → 400/537)

The 397 mix's +10 is all A-class (in-pool); B-class (67 pool-external) needs
lattice re-search, not reranking. `zenzai_constrained_search.cpp` uses the
CondConverter as the **proposer**: draft → cond scores lattice candidates at
worst nodes → prefix-lock override → re-walk → reading-fidelity check → add
pool → argmax three-way `walk+0.5·v2c+0.25·cond` over the full pool
(conservative accept; the n-best 397 candidates are in the pool).

```bash
clang++ -std=c++17 -O2 -I"$ENGINE" -I"$ENGINE/gramambular2" \
  zenzai_constrained_search.cpp "$ENGINE/CondConverterScorer.cpp" \
  "$ENGINE/gramambular2/reading_grid.cpp" "$ENGINE/CorpusBigramContextModel.cpp" \
  "$ENGINE/NeuralLMPathScorer.cpp" "$ENGINE/ParselessLM.cpp" \
  "$ENGINE/ParselessPhraseDB.cpp" "$ENGINE/MemoryMappedFile.cpp" -o /tmp/zenzai_cond
/tmp/zenzai_cond tw538-northstar.tsv ../../../Data/data.txt \
  ../../../Data/word-bigrams.tsv 0.75 \
  ../models/path-char-lstm-spoken-v2c.bin ../models/cond-converter-v2.bin \
  5 8 0.5 0.25 0.5 -2.5
# expect: BASE397_CONTROL 397 · ZENZAI_CORRECT 400 · B_CLASS_FIXED 4/67
#         READING_FIDELITY_FAIL 0/537 ; args = max_bad max_props nuV2c kCond margin logp_thr
```

Full breakdown + the 4 recovered / 3 vetoed sentences:
`../analysis/cond-proposer-constrained-search-tw538.md`.

The same binary sweeps pool-external **acceptance** variants (cached pools, one
run): (A) pool-external walk downweight α, (B) neural two-vote (v2c AND cond
must both prefer the external path by margin m). Best = **two-vote m=1.0 →
401/537** (+1 over the conservative 400; α-downweight collapses = precision-
recall wall). Residual map: of 67 B-class only **7 are reached** by the
proposer, 60 never — the ceiling is now proposal reach, not acceptance.
Table + wall analysis: `../analysis/cond-proposer-acceptance-sweep-tw538.md`.

### A-class attribution + fusion probes

```bash
# T1: FUSION_LOSS vs MODEL_LOSS on A-class 114 (v1 teacher)
clang++ -std=c++17 -O2 -I"$ENGINE" -I"$ENGINE/gramambular2" \
  tw538_a_class_attr.cpp ... -o /tmp/tw538_a_class_attr
/tmp/tw538_a_class_attr tw538-northstar.tsv ../../../Data/data.txt \
  ../../../Data/word-bigrams.tsv 0.75 \
  ../models/path-char-lstm-spoken.bin 0.5 10 \
  ../analysis/tw538-a-attr.tsv
# expect: FUSION_LOSS 28 / MODEL_LOSS 86

# T2a: fusion variants (length-norm / z-score / minmax) harness-only
# tw538_fusion_variants.cpp → both_len_char ν=0.5 → 357 (+1 only)
```

Error decision map + A/B classification (see `../analysis/`):

```bash
clang++ -std=c++17 -O2 -I"$ENGINE" -I"$ENGINE/gramambular2" \
  tw538_decision_map.cpp ...same sources as above... -o /tmp/tw538_decision_map
/tmp/tw538_decision_map tw538-northstar.tsv ../../../Data/data.txt \
  ../../../Data/word-bigrams.tsv 0.75 \
  ../models/path-char-lstm-spoken.bin 0.5 10 \
  ../analysis/tw538-error-map.tsv

python3 ../analysis/classify_tw538_errors.py \
  --map ../analysis/tw538-error-map.tsv \
  --data ../../../Data/data.txt \
  --out-summary ../analysis/tw538-error-summary.txt \
  --out-b-detail ../analysis/tw538-b-class.tsv \
  --out-a-detail ../analysis/tw538-a-class.tsv
```

N / ν scan harness: `nbest_n_nu_scan.cpp`. Helper: `eval_spoken_lstm.sh`.

## Same-path oracle upper bound

For each bigram-miss sentence, ask whether the expected surface can be formed
by only re-picking unigrams on the **same** walk path (no resegmentation).
That is the ceiling for `reselectUnigramValue` / single-node RNN reselect.

```bash
clang++ -std=c++17 -O2 -I../.. -I../../gramambular2 \
  same_path_oracle.cpp ../../gramambular2/reading_grid.cpp \
  ../../CorpusBigramContextModel.cpp ../../ParselessLM.cpp \
  ../../ParselessPhraseDB.cpp ../../MemoryMappedFile.cpp \
  -o /tmp/same_path_oracle
/tmp/same_path_oracle tw-sentences.tsv ../../../Data/data.txt \
  ../../../Data/word-bigrams.tsv 0.75
```

Recorded result (2026-07-09, shipped table, λ=0.75): **66/221** miss sentences
in-oracle (**29.9%**); **155/221** need a different path. Full write-up:
`docs/ngram-rnn-hybrid.md` §2.1.

## Contextual walk (corpus word-bigram ContextModel)

`CorpusBigramContextModel` adds `lambda * PMI(prev, word)` to each candidate's
unigram score inside the DP, so word context participates in the actual
path/choice competition while never generating new text. Pass the PMI table to
run a lambda grid search (lambda is chosen only by benchmark accuracy, never
hand-tuned per case):

```
./build-and-run.sh tw-sentences.tsv <path-to-word-bigrams.tsv>
# single lambda:
./build-and-run.sh tw-sentences.tsv <path-to-word-bigrams.tsv> 0.75
```

Shipped table (`Source/Data/word-bigrams.tsv`, built from zh-TW Wikipedia; see
`../build_word_bigram_table.py`): grid-search optimum **lambda 0.75 -> 44.1%
(174/395)**, +10 cases over baseline, zero regression at lambda 0. The
`他跑得很快` case flips correctly (the bigram makes the walk prefer the
`他 / 跑得 / 很快` segmentation over `他 / 跑 / 的 / 很快`).

**v2.3.0 shipping defaults:** `EnableContextualWalk` is **on** in the app
(lambda 0.75, same numbers as above for a **cold empty personalization
cache**). Soft user personalization must not change these cold-cache
figures; only the bigram table + dictionary decide the north-star metric
when the user cache is empty.

## Building the bigram table (real corpus only)

Frequencies must come from real corpus text (no synthetic / LLM-generated
text). v1 source is zh-TW Wikipedia converted with OpenCC `s2twp`, segmented
with the engine's own unigram lattice (isomorphic units; no jieba / CKIP):

```
python3 ../build_word_bigram_table.py \
    --dump ../corpus/zhwiki-latest-pages-articles.xml.bz2 \
    --data ../../../Data/data.txt \
    --out ../generated/word-bigrams.tsv \
    --max-chars 150000000 --min-count 4 --min-abs-pmi 0.7
```

`--min-abs-pmi` prunes near-zero-PMI rows (which barely affect scoring) to keep
the bundled table small (~25 MB) without losing the informative collocations.
`opencc-python-reimplemented` (pure Python) provides `s2twp`.

## Table slim experiment (2026-07-09, post-filter of shipped TSV)

Shipped table is already `min_count=4` + `min_abs_pmi=0.7` (~25 MB, 1.23M
rows). Raising `|PMI|` further **does not need a wiki rebuild**: use
`../slim_word_bigram_table.py` on the shipped TSV, then re-run this harness.

Commands actually run (cold cache, fixed λ=0.75 unless noted):

```bash
# filter (example)
python3 ../slim_word_bigram_table.py \
  --in ../../../Data/word-bigrams.tsv \
  --out /tmp/word-bigrams-abs2.0.tsv --min-abs-pmi 2.0

# single lambda
./build-and-run.sh tw-sentences.tsv /tmp/word-bigrams-abs2.0.tsv 0.75
# full lambda grid
./build-and-run.sh tw-sentences.tsv /tmp/word-bigrams-abs2.0.tsv
```

| min \|PMI\| | rows | ~size | λ=0.75 accuracy | best λ (grid) |
|------------:|-----:|------:|----------------:|---------------|
| **0.7 shipped** | 1,233,770 | ~24.4 MB | **174/395 (44.1%)** | 0.75 → 174 |
| 1.0 | 934,178 | ~18.7 MB | 170/395 (43.0%) | (not re-gridded) |
| 1.2 | 771,953 | ~15.5 MB | 173/395 (43.8%) | (not re-gridded) |
| 1.5 | 571,175 | ~11.6 MB | **176/395 (44.6%)** | 0.75 → 176 |
| **2.0** | 325,004 | **~6.7 MB** | **177/395 (44.8%)** | **0.75 → 177** |

Notes:

- Non-monotonic at 1.0 / 1.2 (slightly worse than shipped): weak-mid PMI rows
  can help some cases and hurt others; only strong collocations at ≥1.5/2.0
  beat the shipped point on this set.
- Acceptance case `他跑得很快` stays flipped (not in miss list) at λ=0.75 for
  shipped / 1.5 / 2.0.
- **Not yet swapped into `Source/Data/word-bigrams.tsv` or a release** — needs
  product sign-off (DMG size + cold-cache north-star bump). Recommended ship
  candidate: **`min_abs_pmi=2.0`**, keep λ=0.75, ~**6.7 MB**, **+3 sentences**
  vs current shipped table.
- Alternative product path (not measured here): first-run download to
  Application Support instead of embedding (like whisper models).

Note: early `em_reestimate.py` prototypes keyed on the reading column and were
not engine-isomorphic; the correct EM attempt is `../em_reestimate_unigram.py`
(negative result on wiki domain — shelved; see parent `README.md`).
