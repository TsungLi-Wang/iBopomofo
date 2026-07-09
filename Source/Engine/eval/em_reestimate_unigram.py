#!/usr/bin/env python3
"""EM re-estimate the engine unigram table (data.txt) from a REAL corpus.

This replaces the earlier throwaway prototypes (em_reestimate.py / .cpp), which
were broken: they keyed the unigram on the reading column (parts[0]) instead of
the surface value, so every Han lookup missed; the C++ one never even ran the
segmentation; and both emitted a 2-column table that is NOT isomorphic with the
engine's `reading value score` format.

Method (hard-EM / Viterbi-EM over segmentation), reusing the SAME engine-isomorphic
segmenter proven in build_word_bigram_table.py so the token unit matches the
lattice (no jieba / CKIP):

  E-step: segment the corpus into dictionary words using the current per-value
          unigram scores (max-score Viterbi over data.txt surface values) and
          count word (surface value) occurrences.
  M-step: re-estimate each surface value's MARGINAL frequency from the counts,
          interpolate with the old table (weight --mu on the new estimate), then
          distribute the new marginal back across that value's readings *keeping
          the old table's per-reading proportions* (ruling A: only the value
          marginal is re-estimated; polyphone reading split is left untouched).

Total probability mass over the re-estimated set is anchored to the old mass, so
re-estimated and untouched (unseen) entries stay on the same score scale and the
walk's cross-node comparisons remain valid.

RED LINE: the training corpus MUST be real text (zhwiki dump). The 395-sentence
tw benchmark is the final measuring stick ONLY and must never be fed here as
training data (teaching-to-the-test).

data.txt scores are log10 normalized frequencies (see Source/Data/bin_legacy/
buildFreq.py: math.log(..., 10)); all arithmetic here is in log10 to match.

Output is a new data.txt with the identical line order/format; only the score
column of re-estimated Han entries changes. This step only WRITES the new table
to --out; it does not replace Source/Data/data.txt.

Usage:
  em_reestimate_unigram.py --dump corpus/zhwiki-...xml.bz2 \
      --data ../../Data/data.txt --out generated/data-em.txt \
      --max-chars 150000000 --iters 2 --mu 0.7 --opencc s2twp
"""

from __future__ import annotations

import argparse
import math
import sys
import time
from collections import Counter
from pathlib import Path

# Reuse the exact, proven corpus reader + segmenter from the bigram builder so
# the segmentation unit stays identical to the shipped contextual-walk table.
from build_word_bigram_table import extract_runs, load_vocab, viterbi_segment


def load_entries(data_path: Path):
    """Read data.txt preserving order.

    Returns (lines, groups) where `lines` is the list of raw lines (verbatim,
    newline-stripped) and `groups` maps a Han surface value -> list of indices
    into `lines` for entries with that value. Control / kana / punctuation
    values (which never appear in Han corpus runs) are not grouped, so they are
    emitted unchanged.
    """
    lines: list[str] = []
    groups: dict[str, list[int]] = {}
    scores: dict[int, float] = {}
    with data_path.open("r", encoding="utf-8") as handle:
        for raw in handle:
            line = raw.rstrip("\n")
            idx = len(lines)
            lines.append(line)
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) < 3:
                continue
            reading, value, score_s = parts[0], parts[1], parts[2]
            # Only Han values participate: skip control / kana / punctuation.
            if reading.startswith("_") or not _is_han(value):
                continue
            try:
                score = float(score_s)
            except ValueError:
                continue
            groups.setdefault(value, []).append(idx)
            scores[idx] = score
    return lines, groups, scores


def _is_han(s: str) -> bool:
    for ch in s:
        o = ord(ch)
        if not (0x3400 <= o <= 0x4DBF or 0x4E00 <= o <= 0x9FFF
                or 0xF900 <= o <= 0xFAFF or 0x20000 <= o <= 0x2FFFF):
            return False
    return bool(s)


def best_value_scores(groups, scores) -> dict[str, float]:
    """{surface_value: best (max) log10 score across its readings}.

    This is exactly the segmentation vocabulary the engine-isomorphic Viterbi
    uses, kept in sync with the current (possibly re-estimated) scores.
    """
    out: dict[str, float] = {}
    for value, idxs in groups.items():
        out[value] = max(scores[i] for i in idxs)
    return out


def marginal(idxs, scores) -> float:
    """Old marginal probability of a value = sum over its readings of 10^score."""
    return sum(10.0 ** scores[i] for i in idxs)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", required=True, type=Path,
                    help="real corpus (zhwiki .xml.bz2 or plain text)")
    ap.add_argument("--data", required=True, type=Path, help="current data.txt")
    ap.add_argument("--out", required=True, type=Path, help="new data.txt")
    ap.add_argument("--max-chars", type=int, default=150_000_000)
    ap.add_argument("--max-word-len", type=int, default=6)
    ap.add_argument("--opencc", default="s2twp",
                    help="OpenCC config; empty string to skip conversion")
    ap.add_argument("--iters", type=int, default=2,
                    help="hard-EM iterations (re-segment with updated scores)")
    ap.add_argument("--mu", type=float, default=0.7,
                    help="interpolation weight on the new corpus estimate")
    ap.add_argument("--alpha", type=float, default=0.5,
                    help="add-alpha smoothing on corpus counts")
    args = ap.parse_args()

    if args.dump.name.endswith(".tsv"):
        print("REFUSING: --dump looks like a benchmark tsv. The tw benchmark is "
              "the measuring stick, never training data.", file=sys.stderr)
        return 2

    t0 = time.time()
    print(f"[1/5] extract Han runs (cap {args.max_chars:,} chars) from {args.dump.name} ...")
    runs = extract_runs(args.dump, args.max_chars)
    print(f"      {len(runs):,} runs, {sum(len(r) for r in runs):,} chars "
          f"in {time.time()-t0:.1f}s")

    if args.opencc:
        print(f"[2/5] OpenCC convert ({args.opencc}) ...")
        t1 = time.time()
        import opencc
        converter = opencc.OpenCC(args.opencc)
        runs = converter.convert("\n".join(runs)).split("\n")
        print(f"      converted in {time.time()-t1:.1f}s")
    else:
        print("[2/5] OpenCC skipped (--opencc empty)")

    print(f"[3/5] load engine unigram table from {args.data} ...")
    lines, groups, scores = load_entries(args.data)
    _, maxlen = load_vocab(args.data, args.max_word_len)
    maxlen = min(maxlen, args.max_word_len)
    print(f"      {len(lines):,} lines, {len(groups):,} Han surface values")

    # Precompute the old marginal per value once; the M-step anchors to it.
    old_marg = {v: marginal(idxs, scores) for v, idxs in groups.items()}

    print(f"[4/5] hard-EM: {args.iters} iteration(s), mu={args.mu}, alpha={args.alpha}")
    for it in range(1, args.iters + 1):
        ti = time.time()
        vocab = best_value_scores(groups, scores)
        unk = min(vocab.values()) - 1.0
        # E-step: segment + count word (surface value) occurrences in-vocab.
        counts: Counter[str] = Counter()
        ntok = 0
        for run in runs:
            for w in viterbi_segment(run, vocab, maxlen, unk):
                if w in groups:  # only count known Han values
                    counts[w] += 1
                    ntok += 1
        if ntok == 0:
            print("      no tokens counted; aborting.", file=sys.stderr)
            return 3

        # M-step (ruling A). Restrict to values actually seen this iteration.
        seen = [v for v in counts if v in groups]
        mass_old = sum(old_marg[v] for v in seen)
        denom = ntok + args.alpha * len(seen)
        # raw_new(v) is normalized over the seen set; scale to old mass so the
        # re-estimated block keeps the same total probability mass (seen/unseen
        # scale consistency).
        scale = mass_old  # since sum_v raw_new(v) == 1 over `seen`
        delta = 0.0
        for v in seen:
            raw_new = (counts[v] + args.alpha) / denom
            p_new = scale * raw_new
            p_final = args.mu * p_new + (1.0 - args.mu) * old_marg[v]
            if p_final <= 0.0:
                continue
            # Distribute across readings keeping old proportions:
            #   new_score_i = log10(p_final) + old_score_i - log10(old_marg[v])
            shift = math.log10(p_final) - math.log10(old_marg[v])
            for i in groups[v]:
                new_s = scores[i] + shift
                delta += abs(new_s - scores[i])
                scores[i] = new_s
        print(f"      iter {it}: {ntok:,} tokens, {len(seen):,} values re-estimated, "
              f"sum|delta|={delta:.1f} in {time.time()-ti:.1f}s")

    print(f"[5/5] write new table -> {args.out}")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    changed = 0
    with args.out.open("w", encoding="utf-8") as out:
        for idx, line in enumerate(lines):
            if idx in scores:
                parts = line.split()
                new_line = f"{parts[0]} {parts[1]} {scores[idx]:.8f}"
                if new_line != line:
                    changed += 1
                out.write(new_line + "\n")
            else:
                out.write(line + "\n")
    print(f"      wrote {len(lines):,} lines ({changed:,} scores changed) "
          f"in {time.time()-t0:.1f}s total")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
