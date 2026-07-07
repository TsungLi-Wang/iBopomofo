# Rescorer Eval

This directory contains the local harness for the typing-time candidate
rescorer. The rule is strict: the rescorer only chooses among legal candidates
already produced by the engine.

## Baseline

```bash
bash Source/Engine/eval/build-and-run.sh
```

The default case set is `cases.tsv`. Add real mistyped sentences there or pass a
different TSV file:

```bash
bash Source/Engine/eval/build-and-run.sh path/to/cases.tsv
```

Each line is:

```text
readings<TAB>expected_text
```

## External Corpus Model

Generated corpora and models live under ignored directories:

- `Source/Engine/eval/corpus/`
- `Source/Engine/eval/generated/`

Download the Chinese Wikipedia article dump:

```bash
bash Source/Engine/eval/fetch_zhwiki_corpus.sh
```

Train a small model for a quick experiment:

```bash
python3 Source/Engine/eval/train_char_ngram.py \
  --input Source/Engine/eval/corpus/zhwiki-latest-pages-articles.xml.bz2 \
  --output Source/Engine/eval/generated/rescorer-char-ngrams.tsv \
  --max-text-chars 10000000 \
  --min-count 2
```

Run eval with the generated model:

```bash
bash Source/Engine/eval/build-and-run.sh \
  Source/Engine/eval/cases.tsv \
  Source/Engine/eval/generated/rescorer-char-ngrams.tsv
```

To add Taiwan government open-data text, save cleaned `.txt` files under
`Source/Engine/eval/corpus/tw-gov/` and pass the directory as another
`--input` to `train_char_ngram.py`.

## App Integration

The Swift scorer first looks for a bundled `rescorer-char-ngrams.tsv`. If it is
not present, it falls back to deriving a small n-gram model from bundled
`data.txt`. Do not ship a generated model until the eval cases show a measurable
before/after improvement.

## Synthetic 在 / 再 Experiment

Johnny generated a first synthetic corpus under `~/Documents/zaizai/`:

- `zaizai_train.txt`: 200 training sentences, balanced `在` / `再`.
- `zaizai_eval.tsv`: 100 eval rows in `expected_text<TAB>target_char<TAB>note`.

Convert the eval TSV into harness cases:

```bash
python3 Source/Engine/eval/convert_eval_tsv_to_cases.py \
  --input "$HOME/Documents/zaizai/zaizai_eval.tsv" \
  --output Source/Engine/eval/generated/zaizai_eval_cases.tsv \
  --skipped Source/Engine/eval/generated/zaizai_eval_skipped.tsv
```

Train a small synthetic model:

```bash
python3 Source/Engine/eval/train_char_ngram.py \
  --input "$HOME/Documents/zaizai/zaizai_train.txt" \
  --output Source/Engine/eval/generated/zaizai-synthetic.tsv \
  --max-text-chars 1000000 \
  --min-count 1
```

Run the A/B checks:

```bash
bash Source/Engine/eval/build-and-run.sh \
  Source/Engine/eval/generated/zaizai_eval_cases.tsv

bash Source/Engine/eval/build-and-run.sh \
  Source/Engine/eval/generated/zaizai_eval_cases.tsv \
  Source/Engine/eval/generated/zaizai-synthetic.tsv

bash Source/Engine/eval/build-and-run.sh \
  Source/Engine/eval/cases.tsv \
  Source/Engine/eval/generated/zaizai-synthetic.tsv
```

Observed on 2026-06-26:

- `zaizai_eval.tsv`: 99 runnable cases, 1 skipped because it contains `Excel`.
- Fallback model on `zaizai_eval_cases.tsv`: baseline 40/99, rescored 36/99.
- Synthetic model on `zaizai_eval_cases.tsv`: baseline 40/99, rescored 84/99.
- Synthetic model on seed `cases.tsv`: baseline 7/8, rescored 8/8.

Do not commit `~/Documents/zaizai/`, `Source/Engine/eval/generated/`, or the
generated TSV model. Treat this as promising but biased synthetic evidence until
Johnny's real typo cases are added.

## Confusion-Pair Log-Odds Table (在/再)

`ConfusionPairDisambiguator` (the shipping path, hooked into `KeyHandler`'s
`_walk`) uses a character-level log-odds table instead of the generic n-gram
model. Build one from a corpus (plain text or `sentence<TAB>label` TSV; the
first tab field is used):

```bash
python3 Source/Engine/eval/build_confusion_pair_table.py \
  --corpus path/to/train.txt \
  --output Source/Engine/eval/generated/zai-logodds.tsv \
  --threshold 0.5
```

It prints the top alt-leaning entries for manual review plus coverage stats.
Evaluate the table alone with the masked test (hide each 在/再, predict from
neighbors) including a threshold sweep:

```bash
python3 Source/Engine/eval/masked_eval_confusion_pair.py \
  --table Source/Engine/eval/generated/zai-logodds.tsv \
  --eval path/to/eval.tsv
```

Evaluate the actual engine path (walk + disambiguator, exactly what ships) by
passing the table as the third argument of the harness; the n-gram model slot
can be an empty string:

```bash
bash Source/Engine/eval/build-and-run.sh \
  Source/Engine/eval/generated/zaizai_eval_cases.tsv \
  "" \
  Source/Engine/eval/generated/zai-logodds.tsv
```

### Real eval (Johnny's actual mis-selections)

`real-zai-eval.tsv` (committed, next to this README) collects Johnny's real
在/再 mis-selections, target 20-50 rows. Format is the same
`expected_text<TAB>target_char<TAB>note` as the synthetic eval files; header
comments in the file explain the rules (no punctuation, no ASCII). The first
known miss 我再說一次 is pre-seeded.

Convert and run against the shipping table:

```bash
python3 Source/Engine/eval/convert_eval_tsv_to_cases.py \
  --input Source/Engine/eval/real-zai-eval.tsv \
  --output Source/Engine/eval/generated/real-zai-cases.tsv \
  --skipped Source/Engine/eval/generated/real-zai-skipped.tsv

bash Source/Engine/eval/build-and-run.sh \
  Source/Engine/eval/generated/real-zai-cases.tsv \
  "" \
  Source/Data/confusion-pairs.tsv
```

Baseline recorded 2026-07-07 with the shipped v2c table (1 seeded case):
baseline 0/1, disambiguated 0/1 — the known miss, as expected. Once 20+ real
rows exist, use this set (together with the frozen synthetic sets, which must
not regress) to re-sweep the threshold and patch corpus gaps such as the
diluted 再說 context evidence.

Update, same day: Johnny opted out of collecting sentences himself; the miss
was root-caused and fixed with bigram evidence instead (next section). The
seeded case now flips (1/1 with the v6 shipped table).

### Bigram evidence with single-character backoff (2026-07-07, v6 table)

Root cause of the 我再說一次 miss: a single neighbor character cannot
separate 我在說話 (progressive) from 我再說一遍 (again) — both 在說 and
再說 are legitimate, and the discriminating signal (話/什麼 vs 一次/一遍)
sits one character further out. This is a model-expressiveness gap, not a
corpus gap: adding more 說-context sentences moved R[說] around without
fixing the target (v3/v4 experiments).

Fix: the table format gained `LB`/`RB` rows (two-token bigram evidence,
may include one boundary token). Scoring tries the bigram first and backs
off to the single-character `L`/`R` row. Implemented in sync in
`ConfusionPairDisambiguator.cpp` (context read from the flat walk char
sequence, crossing node boundaries), `build_confusion_pair_table.py`
(`context_tokens()`, `--min-bigram-count`, default 2) and
`masked_eval_confusion_pair.py`.

Training corpus: v2 train (480) + v1 train (200) + the committed
`zai-corpus-v3-supplement.tsv` (233; targets 說/講/聊/談 contexts both
ways — round 2 of the supplement patches biases round 1 itself introduced:
LB[^我]/L[面] drifting 再-ward and R[翻] dilution caused false flips on
我在等一個包裹/外面在下雨, fixed with progressive counter-evidence).

```bash
python3 Source/Engine/eval/build_confusion_pair_table.py \
  --corpus <v2_train> <v1_train> Source/Engine/eval/zai-corpus-v3-supplement.tsv \
  --output Source/Engine/eval/generated/zai-logodds-v6.tsv \
  --min-count 1 --min-bigram-count 2 \
  --prior-from-data Source/Data/data.txt --threshold 0.5
```

v6 vs shipped v2c (engine harness, whole sentence):

- old `zaizai_eval_cases.tsv`: 65/99 -> 71/99
- v2 heldout: 42/120 -> 42/120 (identical miss set, verified per-case)
- seed `cases.tsv`: 7/8 -> 7/8 (remaining miss is 意/一, out of scope)
- real eval seed 我再說一次: 0/1 -> 1/1
- live-check (previously device-verified sentences incl. 我再問一次,
  做完再弄, 請再等一下, plus 我在家等你/我在說話/他在說什麼 no-flip
  controls): 8/8
- masked flip precision: heldout 90.3% -> 92.3% (3 -> 2 false flips),
  old eval stays zero false flips

v6 shipped as `Source/Data/confusion-pairs.tsv` (header records the recipe).

### v2 corpus and the recommended training recipe (2026-07-02)

A second synthetic corpus was generated from
`~/Documents/在:再消歧語料生成提示詞.md` (12 categories x 50 sentences,
including trap categories): `~/Documents/zaizai/zaizai_v2_full.tsv`, split
stratified into `zaizai_v2_train.txt` (480) and `zaizai_v2_heldout.tsv` (120,
sentence-disjoint). Two hard-won lessons are baked into the script:

- **Never take the prior from a synthetic corpus.** Its 在:再 ratio is an
  artifact of the category design. Use `--prior-from-data Source/Data/data.txt`
  (prior = engine unigram score difference, -0.912 for 在/再).
- The L/R evidence is a class-conditional likelihood ratio, so the corpus
  class balance cannot leak into it. Use `--min-count 1` for these small,
  deliberately diverse corpora — `--min-count 2` prunes most of the signal.

Recommended build (threshold 0.5 favors precision; every false flip is a new
error, and on real text 在 dominates):

```bash
python3 Source/Engine/eval/build_confusion_pair_table.py \
  --corpus "$HOME/Documents/zaizai/zaizai_v2_train.txt" \
           "$HOME/Documents/zaizai/zaizai_train.txt" \
  --output Source/Engine/eval/generated/zai-logodds-v2c.tsv \
  --min-count 1 --prior-from-data Source/Data/data.txt --threshold 0.5
```

Observed on 2026-07-02 with that table (680 train sentences, 524 entries,
8.2 KB; all corpora are AI-generated — same-source bias applies until real
typo cases exist):

- Masked eval, v2 heldout (120, trap-heavy): baseline always-在 41.7%;
  at threshold 0.5 the table flips 28/70 再 correctly with 3 false flips
  (90.3% flip precision).
- Masked eval, old `zaizai_eval.tsv` (100, older generation session):
  36/50 再 recall with **zero** false flips at threshold 0.5.
- Engine harness (the shipping path), v2 heldout cases, 在/再 slot accuracy:
  baseline 56/120 -> disambiguated 70/120; 15 fixed, 1 "broken" (the one
  break is a cascade: the engine mispicks 客服 as 克服 first, after which
  再處理 is linguistically the better continuation).
- Engine harness, old `zaizai_eval_cases.tsv`: whole-sentence 40/99 -> 65/99.
- Seed `cases.tsv`: 7/8 -> 7/8 (the miss is the 意/一 part of a sentence
  whose 在/再 part is now correct).

Note for engine cases: strip punctuation from sentences before running them
through `convert_eval_tsv_to_cases.py` — readings drop punctuation, so the
expected text must not contain it or nothing ever matches.

A ready-to-bundle copy of the table lives at
`~/Documents/zaizai/confusion-pairs-v2c.tsv`. The app loads
`confusion-pairs.tsv` from the bundle if present (see `KeyHandler.mm`); it is
not bundled yet — per the standing guardrail, ship only after real (not
synthetic) eval cases show a before/after improvement, or after Johnny
explicitly decides the synthetic evidence plus the default-off experimental
gate is enough for a real-machine trial.
