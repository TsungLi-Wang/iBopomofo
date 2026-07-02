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

Observed on 2026-07-02 with a smoke table trained on `zaizai_train.txt`
(200 sentences, threshold 0.5) — same-source bias applies, numbers are for
pipeline validation only:

- Masked eval on `zaizai_eval.tsv`: baseline (always 在) 50/100, table 95/100.
- Engine harness on `zaizai_eval_cases.tsv`: baseline 40/99, disambiguated
  75/99, zero regressions (no B-OK case turned D-MISS). Remaining misses are
  mostly non-在/再 errors (e.g. 意/一) outside this module's scope.
- Seed `cases.tsv`: 7/8 -> 7/8 (the miss is the 意/一 part of a sentence
  whose 在/再 part is now correct).

The app loads `confusion-pairs.tsv` from the bundle if present (see
`KeyHandler.mm`); the resource is not bundled until a table trained on real,
non-synthetic corpus shows a before/after improvement on real eval cases.
