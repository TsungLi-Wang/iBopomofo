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
