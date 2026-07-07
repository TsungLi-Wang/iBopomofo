#!/usr/bin/env python3
"""Masked evaluation for a confusion-pair log-odds table (e.g. 在/再).

For every occurrence of the pair characters in the eval sentences, hide the
character, predict it from the table using only the neighbors, and compare
with the ground truth. Reports three lines:

- baseline: always predict the default character (always 在)
- table:    left(L) + right(R) + prior > threshold -> alt, else default
- a threshold sweep so the shipped threshold can be picked from data

Eval input: one sentence per line; TAB-separated lines use the first field,
so `sentence<TAB>label<TAB>note` files work directly. The ground truth is the
character actually present in the sentence.
"""

import argparse
import sys

from build_confusion_pair_table import (
    context_tokens,
    iter_sentences,
)


def load_table(path):
    pair = None
    prior = 0.0
    threshold = 0.0
    left = {}
    right = {}
    left_bigram = {}
    right_bigram = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line or line.startswith("#"):
                continue
            fields = line.split("\t")
            kind = fields[0]
            if kind == "PAIR" and len(fields) == 4:
                pair = (fields[1], fields[2], fields[3])
            elif kind == "PRIOR" and len(fields) == 2:
                prior = float(fields[1])
            elif kind == "THRESHOLD" and len(fields) == 2:
                threshold = float(fields[1])
            elif kind == "L" and len(fields) == 3:
                left[fields[1]] = float(fields[2])
            elif kind == "R" and len(fields) == 3:
                right[fields[1]] = float(fields[2])
            elif kind == "LB" and len(fields) == 3:
                left_bigram[fields[1]] = float(fields[2])
            elif kind == "RB" and len(fields) == 3:
                right_bigram[fields[1]] = float(fields[2])
    if pair is None:
        raise ValueError(f"表 {path} 缺 PAIR 行")
    return pair, prior, threshold, left, right, left_bigram, right_bigram


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--table", required=True, help="table TSV from "
                        "build_confusion_pair_table.py")
    parser.add_argument("--eval", nargs="+", required=True,
                        help="eval files, one sentence per line")
    parser.add_argument("--sweep", default="-1,-0.5,0,0.5,1,1.5,2",
                        help="comma-separated thresholds to sweep")
    args = parser.parse_args()

    ((_, default_char, alt_char), prior, threshold, left, right,
     left_bigram, right_bigram) = load_table(args.table)
    targets = {default_char, alt_char}

    cases = []  # (score, truth)
    for sentence in iter_sentences(args.eval):
        chars = list(sentence)
        for i, ch in enumerate(chars):
            if ch not in targets:
                continue
            l_tok, r_tok, lb_tok, rb_tok = context_tokens(chars, i)
            # 雙字元證據優先,查不到才退回單字元(backoff,與 C++ 端同步)。
            left_term = (left_bigram[lb_tok]
                         if lb_tok is not None and lb_tok in left_bigram
                         else left.get(l_tok, 0.0))
            right_term = (right_bigram[rb_tok]
                          if rb_tok is not None and rb_tok in right_bigram
                          else right.get(r_tok, 0.0))
            score = left_term + right_term + prior
            cases.append((score, ch))

    if not cases:
        print("eval 檔裡沒有任何目標字。", file=sys.stderr)
        return 1

    n = len(cases)
    n_default = sum(1 for _, truth in cases if truth == default_char)

    def accuracy(th):
        ok = sum(1 for score, truth in cases
                 if (alt_char if score > th else default_char) == truth)
        return ok

    print(f"遮蔽測試：{n} 個目標字出現點 "
          f"({default_char}={n_default}, {alt_char}={n - n_default})")
    print(f"baseline（永遠選{default_char}）: {n_default}/{n} "
          f"({100.0 * n_default / n:.1f}%)")
    ok = accuracy(threshold)
    print(f"查表（表內 threshold={threshold:g}）: {ok}/{n} "
          f"({100.0 * ok / n:.1f}%)")
    print("threshold sweep：")
    for th in (float(t) for t in args.sweep.split(",")):
        ok = accuracy(th)
        print(f"  th={th:+.2f}  {ok}/{n} ({100.0 * ok / n:.1f}%)")

    wrong = [(score, truth) for score, truth in cases
             if (alt_char if score > threshold else default_char) != truth]
    if wrong:
        print(f"\n錯例分數分佈（{len(wrong)} 筆，表內 threshold）：")
        for score, truth in sorted(wrong)[:20]:
            print(f"  truth={truth} score={score:+.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
