# Taiwan Typing Benchmark (north-star metric)

Full-sentence top-1 character accuracy on clean Taiwan sentences: convert the
reading key sequence with the engine `walk()` and compare the whole string to
the expected text. This is the single objective judge for engine changes.

- `tw-sentences.tsv`: `readings<TAB>expected_text`, 395 cases (no punctuation;
  the C++ harness feeds BPMF syllables only).
- `tw_benchmark.cpp` / `build-and-run.sh`: compile against the real dictionary
  and print baseline accuracy. Results are read via `walk().chosenValueAt(i)`,
  the only correct way to read a walk that used a `ContextModel` (the DP records
  its choice in `selectedUnigramIndices` without mutating the nodes, so
  `valuesAsStrings()` / `node->value()` do not reflect it).

## Baseline

```
./build-and-run.sh
```

Unigram-only walk: **41.5% (164/395)**.

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
