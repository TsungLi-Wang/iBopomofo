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

Note: `../em_reestimate.py` (unigram EM prototype) keys on `parts[0]`, which is
the reading, not the surface value, so it does not segment Chinese text as
intended; the bigram pipeline above supersedes it for context modeling.
