#!/usr/bin/env python3
"""Build a word-level bigram context table from a real corpus.

Pipeline (all statistics come from REAL corpus text; synthetic / LLM-generated
text is never used for frequencies):

  1. Extract Han-character runs from a zhwiki XML dump (or plain text).
  2. Convert to Traditional Taiwanese word forms with OpenCC (s2twp).
  3. Segment each run into dictionary words using the ENGINE's own unigram
     scores (Viterbi max-score segmentation over data.txt surface values). This
     keeps the segmentation unit isomorphic with the engine lattice; no jieba /
     CKIP, which would introduce a different tokenisation unit.
  4. Count word unigrams and adjacent word bigrams within each run.
  5. Emit a TSV of pointwise mutual information (PMI) per bigram:
         prev <TAB> word <TAB> pmi
     where pmi = log10( c(prev,word) * N / (c(prev) * c(word)) ).
     PMI = log P(word|prev) - log P(word); it is the contextual adjustment on
     top of the unigram score and is independent of the interpolation weight
     lambda, so lambda can be grid-searched without regenerating the table.

The C++ ReadingGrid::ContextModel adds lambda * PMI to the unigram score of
each candidate during walk(), so context can influence the actual path/choice
competition (not a post-hoc fix), while never generating new text: only words
that already exist among a node's unigrams are ever scored.

Usage:
  build_word_bigram_table.py --dump corpus/zhwiki-...xml.bz2 \
      --data ../../Data/data.txt --out generated/word-bigrams.tsv \
      --max-chars 40000000 --min-count 4 [--opencc s2twp]
"""

from __future__ import annotations

import argparse
import bz2
import html
import math
import re
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Iterator

HAN_RE = re.compile(r"[㐀-䶿一-鿿豈-﫿]+")
XML_TAG_RE = re.compile(r"<[^>]+>")
WIKI_TEMPLATE_RE = re.compile(r"\{\{[^{}]*\}\}")
WIKI_LINK_RE = re.compile(r"\[\[(?:[^\]|]*\|)?([^\]]+)\]\]")
URL_RE = re.compile(r"https?://\S+")

HEADER = "# laowang-word-bigram-v1"


def clean_line(line: str) -> str:
    line = html.unescape(line)
    line = XML_TAG_RE.sub("", line)
    line = WIKI_TEMPLATE_RE.sub("", line)
    line = WIKI_LINK_RE.sub(r"\1", line)
    line = URL_RE.sub("", line)
    return line


def open_text(path: Path) -> Iterator[str]:
    if path.suffix == ".bz2":
        try:
            with bz2.open(path, "rt", encoding="utf-8", errors="ignore") as handle:
                yield from handle
        except EOFError:
            print(f"warning: {path} truncated; using decoded prefix", file=sys.stderr)
        return
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        yield from handle


def extract_runs(path: Path, max_chars: int) -> list[str]:
    runs: list[str] = []
    consumed = 0
    for line in open_text(path):
        for match in HAN_RE.finditer(clean_line(line)):
            text = match.group(0)
            if len(text) >= 2:
                runs.append(text)
                consumed += len(text)
        if consumed >= max_chars:
            break
    return runs


def load_vocab(data_path: Path, max_word_len: int) -> tuple[dict[str, float], int]:
    """Return {surface_value: best_unigram_log10_score} and the max word length.

    data.txt lines are `reading value score`; keep the best (highest) score per
    surface value across readings. Control / punctuation entries never appear in
    Han runs, so they are harmless if present.
    """
    scores: dict[str, float] = {}
    maxlen = 1
    with data_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) < 3:
                continue
            value = parts[1]
            try:
                score = float(parts[2])
            except ValueError:
                continue
            if len(value) > max_word_len:
                continue
            if value not in scores or score > scores[value]:
                scores[value] = score
            maxlen = max(maxlen, len(value))
    return scores, maxlen


def viterbi_segment(text: str, scores: dict[str, float], maxlen: int,
                    unk_score: float) -> list[str]:
    n = len(text)
    if n == 0:
        return []
    dp = [-math.inf] * (n + 1)
    back = [(-1, "")] * (n + 1)
    dp[0] = 0.0
    for i in range(1, n + 1):
        lo = max(0, i - maxlen)
        for j in range(lo, i):
            word = text[j:i]
            sc = scores.get(word)
            if sc is None:
                # Only allow unknown single characters, so segmentation never
                # invents multi-char words that are not in the dictionary.
                if i - j > 1:
                    continue
                sc = unk_score
            cand = dp[j] + sc
            if cand > dp[i]:
                dp[i] = cand
                back[i] = (j, word)
    words: list[str] = []
    i = n
    while i > 0:
        j, word = back[i]
        if word:
            words.append(word)
        i = j
    words.reverse()
    return words


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", required=True, type=Path)
    ap.add_argument("--data", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--max-chars", type=int, default=40_000_000)
    ap.add_argument("--min-count", type=int, default=4)
    ap.add_argument("--max-word-len", type=int, default=6)
    ap.add_argument("--opencc", default="s2twp",
                    help="OpenCC config; empty string to skip conversion")
    ap.add_argument("--pmi-clip", type=float, default=8.0,
                    help="clip |PMI| to this to avoid rare-pair overfitting")
    ap.add_argument("--min-abs-pmi", type=float, default=0.0,
                    help="drop rows with |PMI| below this; near-zero PMI barely "
                         "affects scoring, so pruning keeps the bundled table "
                         "small while retaining the informative collocations")
    args = ap.parse_args()

    t0 = time.time()
    print(f"[1/5] extract Han runs (cap {args.max_chars:,} chars) ...")
    runs = extract_runs(args.dump, args.max_chars)
    total_chars = sum(len(r) for r in runs)
    print(f"      {len(runs):,} runs, {total_chars:,} chars in {time.time()-t0:.1f}s")

    if args.opencc:
        print(f"[2/5] OpenCC convert ({args.opencc}) ...")
        t1 = time.time()
        import opencc
        converter = opencc.OpenCC(args.opencc)
        # Convert in one batch joined by newline (OpenCC preserves newlines).
        runs = converter.convert("\n".join(runs)).split("\n")
        print(f"      converted in {time.time()-t1:.1f}s")
    else:
        print("[2/5] OpenCC skipped (--opencc empty)")

    print(f"[3/5] load engine vocab from {args.data} ...")
    scores, maxlen = load_vocab(args.data, args.max_word_len)
    maxlen = min(maxlen, args.max_word_len)
    unk_score = min(scores.values()) - 1.0
    print(f"      {len(scores):,} surface values, max word len {maxlen}, "
          f"unk_score {unk_score:.2f}")

    print("[4/5] engine-isomorphic Viterbi segmentation + bigram counting ...")
    t2 = time.time()
    uni: Counter[str] = Counter()
    bi: Counter[tuple[str, str]] = Counter()
    ntok = 0
    for idx, run in enumerate(runs):
        words = viterbi_segment(run, scores, maxlen, unk_score)
        prev = None
        for w in words:
            uni[w] += 1
            ntok += 1
            if prev is not None:
                bi[(prev, w)] += 1
            prev = w
        if idx and idx % 200_000 == 0:
            print(f"      {idx:,}/{len(runs):,} runs ...")
    print(f"      {ntok:,} tokens, {len(uni):,} word types, "
          f"{len(bi):,} bigram types in {time.time()-t2:.1f}s")

    print(f"[5/5] PMI (min-count {args.min_count}) -> {args.out}")
    N = float(ntok)
    rows: list[tuple[str, str, float]] = []
    for (prev, word), c in bi.items():
        if c < args.min_count:
            continue
        cp = uni[prev]
        cw = uni[word]
        if cp == 0 or cw == 0:
            continue
        pmi = math.log10((c * N) / (cp * cw))
        if pmi > args.pmi_clip:
            pmi = args.pmi_clip
        elif pmi < -args.pmi_clip:
            pmi = -args.pmi_clip
        if abs(pmi) < args.min_abs_pmi:
            continue
        rows.append((prev, word, pmi))
    rows.sort(key=lambda r: (r[0], -r[2]))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as handle:
        handle.write(HEADER + "\n")
        handle.write(f"# source={args.dump.name} opencc={args.opencc or 'none'} "
                     f"max_chars={args.max_chars} tokens={ntok} "
                     f"min_count={args.min_count} pmi_clip={args.pmi_clip}\n")
        for prev, word, pmi in rows:
            handle.write(f"{prev}\t{word}\t{pmi:.5f}\n")
    print(f"      wrote {len(rows):,} bigram rows in {time.time()-t0:.1f}s total")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
