#!/usr/bin/env python3
"""Build a log-odds lookup table for a homophone confusion pair (e.g. 在/再).

Method: for every occurrence of the pair characters in the corpus, count the
left neighbor L and right neighbor R. The table stores, per neighbor token,
the class-conditional likelihood ratio

    left(L)  = log((C(L, alt) + a) / (C(alt) + aV)) -
               log((C(L, def) + a) / (C(def) + aV))
    right(R) = analogous with the right neighbor

which is deliberately independent of the corpus class balance: a synthetic
corpus is built per category, so its 在:再 ratio is an artifact and must not
leak into the evidence. The prior carries the real-world class ratio instead;
by default it is derived from the engine dictionary's own unigram scores
(--prior-from-data path/to/data.txt gives prior = score(alt) - score(def),
naturally favoring the frequent default), or it can be set with --prior.

At inference time, score(alt) = left + right + prior; if the score exceeds
the threshold the alternative character wins, otherwise the default stays.
The default should be the character that is correct most of the time
(for 在/再 the default is 在).

The left/right terms use two-character bigram evidence (LB/RB rows) with
backoff to the single-character evidence (L/R rows): a single neighbor
cannot separate 我在說話 from 我再說一遍 — the discriminating signal (話
vs 一) sits one character further out, so RB[說一] must be able to override
R[說]. When the bigram (including one boundary token) is not in the table,
the single-character row applies as before.

Corpus input: one sentence per line. If a line contains TAB characters only
the first field is used, so both plain text and labelled TSV
(sentence<TAB>label...) work as-is.

Token normalization MUST stay in sync with
Source/Engine/ConfusionPairDisambiguator.cpp (NormalizeContextToken).
"""

import argparse
import math
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta

BEGIN_TOKEN = "^"
END_TOKEN = "$"
DIGIT_TOKEN = "#D"
ALPHA_TOKEN = "#A"
OTHER_TOKEN = "#O"

# Keep in sync with ConfusionPairDisambiguator.cpp.
KEPT_PUNCTUATION = set("，。！？、；：…—（）「」『』,.!?;:()")


def is_cjk(ch: str) -> bool:
    cp = ord(ch)
    return (
        0x4E00 <= cp <= 0x9FFF
        or 0x3400 <= cp <= 0x4DBF
        or 0xF900 <= cp <= 0xFAFF
    )


def normalize_token(ch: str) -> str:
    if is_cjk(ch) or ch in KEPT_PUNCTUATION:
        return ch
    if ch.isdigit() or "０" <= ch <= "９":
        return DIGIT_TOKEN
    if ch.isascii() and ch.isalpha():
        return ALPHA_TOKEN
    return OTHER_TOKEN


def context_tokens(chars, i):
    """Context of chars[i]: (left, right, left-bigram, right-bigram).

    Bigrams may include one boundary token and are None when there is no
    real neighbor character on that side. MUST stay in sync with the flat
    walk-context logic in ConfusionPairDisambiguator.cpp.
    """
    n = len(chars)
    left = normalize_token(chars[i - 1]) if i > 0 else BEGIN_TOKEN
    right = normalize_token(chars[i + 1]) if i + 1 < n else END_TOKEN
    left_bigram = None
    if i >= 1:
        l2 = normalize_token(chars[i - 2]) if i >= 2 else BEGIN_TOKEN
        left_bigram = l2 + left
    right_bigram = None
    if i + 1 < n:
        r2 = normalize_token(chars[i + 2]) if i + 2 < n else END_TOKEN
        right_bigram = right + r2
    return left, right, left_bigram, right_bigram


def iter_sentences(paths):
    for path in paths:
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.startswith("#"):
                    continue
                sentence = line.rstrip("\n").split("\t")[0].strip()
                if sentence:
                    yield sentence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", nargs="+", required=True,
                        help="corpus files, one sentence per line "
                             "(TSV allowed; first field is used)")
    parser.add_argument("--output", required=True, help="output table TSV")
    parser.add_argument("--reading", default="ㄗㄞˋ",
                        help="Bopomofo reading of the pair")
    parser.add_argument("--default-char", default="在",
                        help="character that wins without strong evidence")
    parser.add_argument("--alt-char", default="再",
                        help="character that needs contextual evidence")
    parser.add_argument("--alpha", type=float, default=0.5,
                        help="add-alpha smoothing constant")
    parser.add_argument("--prior", type=float, default=None,
                        help="prior log-odds written into the table; "
                             "overrides --prior-from-data")
    parser.add_argument("--prior-from-data", metavar="DATA_TXT",
                        help="derive the prior from the engine dictionary: "
                             "score(alt) - score(default) for the pair "
                             "reading in data.txt")
    parser.add_argument("--threshold", type=float, default=0.0,
                        help="decision threshold written into the table")
    parser.add_argument("--min-count", type=int, default=2,
                        help="drop neighbor entries seen fewer times in total")
    parser.add_argument("--min-bigram-count", type=int, default=2,
                        help="drop bigram entries seen fewer times in total "
                             "(bigrams are sparse; 1 overfits single sentences)")
    parser.add_argument("--min-abs-logodds", type=float, default=0.05,
                        help="drop entries with |log-odds| below this")
    parser.add_argument("--top", type=int, default=50,
                        help="print this many strongest alt-leaning entries")
    args = parser.parse_args()

    default_char, alt_char = args.default_char, args.alt_char
    targets = {default_char, alt_char}

    left_counts = defaultdict(lambda: defaultdict(int))
    right_counts = defaultdict(lambda: defaultdict(int))
    left_bigram_counts = defaultdict(lambda: defaultdict(int))
    right_bigram_counts = defaultdict(lambda: defaultdict(int))
    totals = defaultdict(int)
    sentences = 0

    for sentence in iter_sentences(args.corpus):
        sentences += 1
        chars = list(sentence)
        for i, ch in enumerate(chars):
            if ch not in targets:
                continue
            left, right, left_bigram, right_bigram = context_tokens(chars, i)
            left_counts[left][ch] += 1
            right_counts[right][ch] += 1
            if left_bigram is not None:
                left_bigram_counts[left_bigram][ch] += 1
            if right_bigram is not None:
                right_bigram_counts[right_bigram][ch] += 1
            totals[ch] += 1

    occurrences = totals[default_char] + totals[alt_char]
    if occurrences == 0:
        print("語料裡找不到任何目標字，請檢查 --corpus。", file=sys.stderr)
        return 1

    alpha = args.alpha

    if args.prior is not None:
        prior = args.prior
        prior_source = "--prior"
    elif args.prior_from_data:
        scores = {}
        with open(args.prior_from_data, encoding="utf-8") as f:
            for line in f:
                parts = line.split()
                if (len(parts) == 3 and parts[0] == args.reading
                        and parts[1] in targets):
                    scores[parts[1]] = float(parts[2])
        if default_char not in scores or alt_char not in scores:
            print(f"{args.prior_from_data} 裡找不到 {args.reading} 的 "
                  f"{default_char}/{alt_char} unigram。", file=sys.stderr)
            return 1
        prior = scores[alt_char] - scores[default_char]
        prior_source = f"engine data.txt ({scores})"
    else:
        # Corpus ratio as a last resort; for per-category synthetic corpora
        # this ratio is an artifact of the category design, prefer
        # --prior-from-data.
        prior = math.log((totals[alt_char] + alpha) /
                         (totals[default_char] + alpha))
        prior_source = "corpus ratio (beware: synthetic corpora distort this)"

    def build_rows(counts, vocab_size, min_count=None):
        if min_count is None:
            min_count = args.min_count
        rows = {}
        for token, by_char in counts.items():
            c_default = by_char[default_char]
            c_alt = by_char[alt_char]
            if c_default + c_alt < min_count:
                continue
            # Class-conditional likelihood ratio: independent of the corpus
            # 在:再 balance, which for synthetic corpora is meaningless.
            logodds = (
                math.log((c_alt + alpha) /
                         (totals[alt_char] + alpha * vocab_size))
                - math.log((c_default + alpha) /
                           (totals[default_char] + alpha * vocab_size)))
            if abs(logodds) < args.min_abs_logodds:
                continue
            rows[token] = (logodds, c_default, c_alt)
        return rows

    left_rows = build_rows(left_counts, len(left_counts))
    right_rows = build_rows(right_counts, len(right_counts))
    left_bigram_rows = build_rows(
        left_bigram_counts, len(left_bigram_counts), args.min_bigram_count)
    right_bigram_rows = build_rows(
        right_bigram_counts, len(right_bigram_counts), args.min_bigram_count)

    now = datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")
    with open(args.output, "w", encoding="utf-8") as out:
        out.write(f"# confusion pair table generated {now}\n")
        out.write(f"# corpus: {' '.join(args.corpus)}\n")
        out.write(f"# sentences={sentences} occurrences={occurrences} "
                  f"C({default_char})={totals[default_char]} "
                  f"C({alt_char})={totals[alt_char]} alpha={alpha}\n")
        out.write(f"PAIR\t{args.reading}\t{default_char}\t{alt_char}\n")
        out.write(f"PRIOR\t{prior:.6f}\n")
        out.write(f"THRESHOLD\t{args.threshold:.6f}\n")
        for token, (logodds, _, _) in sorted(left_rows.items()):
            out.write(f"L\t{token}\t{logodds:.6f}\n")
        for token, (logodds, _, _) in sorted(right_rows.items()):
            out.write(f"R\t{token}\t{logodds:.6f}\n")
        for token, (logodds, _, _) in sorted(left_bigram_rows.items()):
            out.write(f"LB\t{token}\t{logodds:.6f}\n")
        for token, (logodds, _, _) in sorted(right_bigram_rows.items()):
            out.write(f"RB\t{token}\t{logodds:.6f}\n")

    kept = (len(left_rows) + len(right_rows)
            + len(left_bigram_rows) + len(right_bigram_rows))
    print(f"句數 {sentences}、目標字出現 {occurrences} 次 "
          f"({default_char}={totals[default_char]}, {alt_char}={totals[alt_char]})")
    print(f"表已寫入 {args.output}：left {len(left_rows)} 條、"
          f"right {len(right_rows)} 條、left-bigram {len(left_bigram_rows)} 條、"
          f"right-bigram {len(right_bigram_rows)} 條（共 {kept}）")
    print(f"prior={prior:.3f}（來源：{prior_source}）")

    def coverage(counts, rows):
        seen = sum(sum(by_char.values()) for by_char in counts.values())
        covered = sum(sum(counts[t].values()) for t in rows)
        return covered / seen if seen else 0.0

    print(f"coverage：left {coverage(left_counts, left_rows):.1%}、"
          f"right {coverage(right_counts, right_rows):.1%}")

    review = []
    for side, rows in (("L", left_rows), ("R", right_rows)):
        for token, (logodds, c_default, c_alt) in rows.items():
            review.append((logodds, side, token, c_default, c_alt))
    review.sort(reverse=True)
    print(f"\n最偏「{alt_char}」的前 {args.top} 條（人工 review 用）：")
    for logodds, side, token, c_default, c_alt in review[: args.top]:
        pattern = (f"{token}{alt_char}" if side == "L" else f"{alt_char}{token}")
        print(f"  {side} {token!r:6} {logodds:+.3f}  "
              f"[{pattern}]  {default_char}={c_default} {alt_char}={c_alt}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
