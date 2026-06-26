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
