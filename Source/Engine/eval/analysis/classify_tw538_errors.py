#!/usr/bin/env python3
"""Classify tw538 error-map rows into A/B buckets with dictionary checks.

B (out of pool, incorrect):
  - missing_lexicon: longest-match segmentation of gold hits a OOV char/word
  - path_locked: all gold segments in lexicon AND their top readings concatenate
    to the input reading (so lattice *could* host the words) but gold not in pool
  - reading_mismatch: segments in lexicon but top-reading concat != input reading
  - other

A (in pool, scorer picked wrong):
  Pattern heuristics on (gold, rerank_out) confusion.

Usage:
  python3 classify_tw538_errors.py \\
    --map ../analysis/tw538-error-map.tsv \\
    --data ../../../Data/data.txt \\
    --out-summary tw538-error-summary.txt \\
    --out-b-detail tw538-b-class.tsv \\
    --out-a-detail tw538-a-class.tsv
"""

from __future__ import annotations

import argparse
import re
from collections import Counter, defaultdict
from pathlib import Path

HAN = re.compile(r"[\u4e00-\u9fff]")


def load_lexicon(data_path: Path) -> dict[str, list[tuple[float, str]]]:
    """word -> [(score, reading), ...] sorted desc by score."""
    w2r: dict[str, list[tuple[float, str]]] = defaultdict(list)
    for line in data_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(" ")
        if len(parts) < 3:
            continue
        reading, value = parts[0], parts[1]
        if reading.startswith("_"):
            continue
        try:
            score = float(parts[-1])
        except ValueError:
            continue
        if value and all("\u4e00" <= c <= "\u9fff" for c in value):
            w2r[value].append((score, reading))
    for k in w2r:
        w2r[k].sort(reverse=True)
    return w2r


def build_trie(words: list[str]) -> dict:
    root: dict = {}
    for w in words:
        node = root
        for ch in w:
            node = node.setdefault(ch, {})
        node["$"] = True
    return root


def longest_match(text: str, trie: dict, max_len: int = 8) -> list[str] | None:
    i, n = 0, len(text)
    out: list[str] = []
    while i < n:
        node = trie
        best = -1
        j = i
        while j < n and j - i < max_len:
            ch = text[j]
            if ch not in node:
                break
            node = node[ch]
            j += 1
            if "$" in node:
                best = j
        if best < 0:
            ch = text[i]
            if ch in trie and "$" in trie[ch]:
                out.append(ch)
                i += 1
                continue
            return None
        out.append(text[i:best])
        i = best
    return out


def classify_b(gold: str, reading: str, w2r: dict, trie: dict) -> tuple[str, str]:
    """Return (label, detail)."""
    segs = longest_match(gold, trie)
    if segs is None:
        # find first OOV span greedily
        oov = []
        i = 0
        while i < len(gold):
            if gold[i] not in trie or "$" not in trie.get(gold[i], {}):
                # single char not in dict
                if gold[i] not in w2r:
                    oov.append(gold[i])
            i += 1
        return "missing_lexicon", "seg_fail oov_chars=" + ",".join(oov[:8])

    oov_words = [w for w in segs if w not in w2r]
    if oov_words:
        return "missing_lexicon", "oov_words=" + ",".join(oov_words)

    # top readings concat
    tops = []
    for w in segs:
        tops.append(w2r[w][0][1])
    concat = "-".join(tops)
    if concat == reading:
        return "path_locked", "segs=" + "/".join(segs)
    # try any reading combination? Too expensive. Check if reading can be
    # partitioned into per-seg readings that exist in lexicon for that word.
    syls = reading.split("-")
    if _can_align_readings(segs, syls, w2r):
        return "path_locked", "align_ok segs=" + "/".join(segs)
    return "reading_mismatch", f"top={concat} input={reading} segs=" + "/".join(segs)


def _can_align_readings(
    segs: list[str], syls: list[str], w2r: dict
) -> bool:
    """DP: can we cover syls by concatenating some reading of each seg in order?"""
    n = len(segs)
    m = len(syls)
    # dp[i][j] = can cover first j syllables with first i segs
    dp = [False] * (m + 1)
    dp[0] = True
    for i, w in enumerate(segs):
        ndp = [False] * (m + 1)
        readings = [r for _, r in w2r[w]]
        for j in range(m + 1):
            if not dp[j]:
                continue
            for rd in readings:
                rs = rd.split("-") if rd else []
                k = len(rs)
                if j + k <= m and syls[j : j + k] == rs:
                    ndp[j + k] = True
        dp = ndp
    return dp[m]


def classify_a(gold: str, pred: str) -> str:
    """Heuristic confusion pattern for in-pool scorer errors."""
    if gold == pred:
        return "none"
    # same length char-wise?
    g_chars = list(gold)
    p_chars = list(pred)
    if len(g_chars) == len(p_chars):
        diffs = [(gc, pc) for gc, pc in zip(g_chars, p_chars) if gc != pc]
        if len(diffs) == 1:
            gc, pc = diffs[0]
            pair = f"{pc}→{gc}"
            # classic particles
            if {gc, pc} <= set("的得地"):
                return f"particle_的得地({pair})"
            if {gc, pc} <= set("在再"):
                return f"particle_在再({pair})"
            if {gc, pc} <= set("他她它"):
                return f"pronoun_他她它({pair})"
            if {gc, pc} <= set("做作坐座"):
                return f"homophone_做作坐座({pair})"
            if {gc, pc} <= set("是事市世士"):
                return f"homophone_是事市({pair})"
            # measure words common set
            measures = set("個支隻枝條張片本把杯碗台臺輛架")
            if gc in measures or pc in measures:
                return f"measure_word({pair})"
            return f"single_char_swap({pair})"
        if 2 <= len(diffs) <= 3:
            return f"multi_char_swap(n={len(diffs)})"
        return f"same_len_many_diff(n={len(diffs)})"
    # length differs: likely segmentation / multi-char phrase
    if abs(len(g_chars) - len(p_chars)) <= 2:
        # check if gold multi-char was split into singles in pred
        return "len_diff_seg_or_phrase"
    return "len_diff_other"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--map", type=Path, required=True)
    ap.add_argument("--data", type=Path, required=True)
    ap.add_argument("--out-summary", type=Path, required=True)
    ap.add_argument("--out-b-detail", type=Path, required=True)
    ap.add_argument("--out-a-detail", type=Path, required=True)
    args = ap.parse_args()

    w2r = load_lexicon(args.data)
    trie = build_trie(list(w2r.keys()))
    print(f"lexicon_words={len(w2r)}", flush=True)

    rows = []
    for line in args.map.read_text(encoding="utf-8").splitlines()[1:]:
        parts = line.split("\t")
        if len(parts) < 7:
            continue
        rows.append(
            {
                "id": parts[0],
                "reading": parts[1],
                "gold": parts[2],
                "walk": parts[3],
                "rerank": parts[4],
                "in_pool": parts[5],
                "correct": parts[6],
            }
        )
    print(f"map_rows={len(rows)}", flush=True)

    total = len(rows)
    correct = sum(1 for r in rows if r["correct"] == "Y")
    in_pool = sum(1 for r in rows if r["in_pool"] == "Y")
    a_rows = [r for r in rows if r["in_pool"] == "Y" and r["correct"] == "N"]
    b_rows = [r for r in rows if r["in_pool"] == "N" and r["correct"] == "N"]
    # in pool and correct is fine; out pool and correct shouldn't happen if gold
    # not in pool but scorer somehow output gold - count as anomaly
    anomaly = [r for r in rows if r["in_pool"] == "N" and r["correct"] == "Y"]

    b_labels = Counter()
    a_labels = Counter()

    with args.out_b_detail.open("w", encoding="utf-8") as fb:
        fb.write("id\tgold\treading\trerank\tb_label\tdetail\n")
        for r in b_rows:
            label, detail = classify_b(r["gold"], r["reading"], w2r, trie)
            b_labels[label] += 1
            fb.write(
                f"{r['id']}\t{r['gold']}\t{r['reading']}\t{r['rerank']}\t"
                f"{label}\t{detail}\n"
            )

    with args.out_a_detail.open("w", encoding="utf-8") as fa:
        fa.write("id\tgold\trerank\twalk\ta_label\n")
        for r in a_rows:
            label = classify_a(r["gold"], r["rerank"])
            a_labels[label] += 1
            fa.write(
                f"{r['id']}\t{r['gold']}\t{r['rerank']}\t{r['walk']}\t{label}\n"
            )

    lines = []
    def p(msg=""):
        lines.append(msg)
        print(msg, flush=True)

    p("=== tw538 error classification summary ===")
    p(f"total={total}")
    p(f"correct={correct} ({100*correct/total:.1f}%)")
    p(f"in_pool={in_pool} ({100*in_pool/total:.1f}%)")
    p(f"A_pool_scorer_wrong={len(a_rows)} ({100*len(a_rows)/total:.1f}%)")
    p(f"B_pool_miss={len(b_rows)} ({100*len(b_rows)/total:.1f}%)")
    p(f"anomaly_outpool_but_correct={len(anomaly)}")
    p("")
    p("--- B class (pool miss) ---")
    for k, v in b_labels.most_common():
        p(f"B\t{k}\t{v}\t{100*v/max(1,len(b_rows)):.1f}%_of_B")
    p("")
    p("--- A class (in-pool scorer wrong) top patterns ---")
    for k, v in a_labels.most_common(40):
        p(f"A\t{k}\t{v}\t{100*v/max(1,len(a_rows)):.1f}%_of_A")
    # aggregate A super-categories
    super_a = Counter()
    for k, v in a_labels.items():
        if k.startswith("particle_"):
            super_a["particle_family"] += v
        elif k.startswith("measure_"):
            super_a["measure_word"] += v
        elif k.startswith("single_char_swap"):
            super_a["single_char_swap"] += v
        elif k.startswith("multi_char_swap"):
            super_a["multi_char_swap"] += v
        elif k.startswith("homophone_"):
            super_a["homophone_family"] += v
        elif k.startswith("pronoun_"):
            super_a["pronoun_family"] += v
        elif k.startswith("len_diff"):
            super_a["len_diff_seg_phrase"] += v
        else:
            super_a["other"] += v
    p("")
    p("--- A super-categories ---")
    for k, v in super_a.most_common():
        p(f"A_super\t{k}\t{v}\t{100*v/max(1,len(a_rows)):.1f}%_of_A")

    args.out_summary.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {args.out_summary}", flush=True)
    print(f"wrote {args.out_b_detail}", flush=True)
    print(f"wrote {args.out_a_detail}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
