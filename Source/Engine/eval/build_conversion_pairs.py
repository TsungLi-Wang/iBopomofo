#!/usr/bin/env python3
"""Build (left_context, reading) → word pairs for conditional conversion.

Uses real PTT spoken text + dictionary (data.txt) longest-match segmentation
and top-score reading lookup. No synthetic / LLM pairs.

Discard rules (noise control):
  - mainland marker lines (視頻/質量/信息… as line filter — keep 視頻 as TW term
    is OK; markers are PRC-style co-occurrence lines from prior pipeline)
  - unknown chars / words not in dictionary
  - multi-reading words when top-2 scores are too close (ambiguous)
  - system readings (_punctuation_, _letter_, …)
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

HAN_RE = re.compile(r"[\u4e00-\u9fff]+")

# Line-level PRC markers (same spirit as spoken A/B filter).
MAINLAND_MARKERS = [
    "質量",
    "信息",
    "軟件",
    "網絡",
    "攝像頭",
    "打印機",
    "鼠標",
    "硬盤",
    "程序員",
    "博客",
    "短信",
    "默認",
]


def load_dict(data_path: Path):
    """reading -> [(score, value)], value -> [(score, reading)]."""
    r2w: dict[str, list[tuple[float, str]]] = defaultdict(list)
    w2r: dict[str, list[tuple[float, str]]] = defaultdict(list)
    for line in data_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(" ")
        if len(parts) < 3:
            continue
        reading, value = parts[0], parts[1]
        try:
            score = float(parts[-1])
        except ValueError:
            continue
        if reading.startswith("_"):
            continue
        if not value or not all("\u4e00" <= c <= "\u9fff" for c in value):
            continue
        r2w[reading].append((score, value))
        w2r[value].append((score, reading))
    # sort by score desc
    for k in r2w:
        r2w[k].sort(reverse=True)
    for k in w2r:
        w2r[k].sort(reverse=True)
    return r2w, w2r


def best_reading(
    word: str, w2r: dict, ambig_gap: float
) -> tuple[str | None, str | None]:
    """Return (reading, discard_reason)."""
    rs = w2r.get(word)
    if not rs:
        return None, "no_reading"
    if len(rs) == 1:
        return rs[0][1], None
    top_sc, top_rd = rs[0]
    second_sc = rs[1][0]
    if top_sc - second_sc < ambig_gap:
        return None, "ambig_reading"
    return top_rd, None


def build_trie(words: list[str]) -> dict:
    """Char trie for longest-match. Node: {ch: child, '$': True if end}."""
    root: dict = {}
    for w in words:
        node = root
        for ch in w:
            node = node.setdefault(ch, {})
        node["$"] = True
    return root


def longest_match_segment(text: str, trie: dict, max_len: int = 8) -> list[str] | None:
    """Greedy left-to-right longest match. Returns None if stuck."""
    i = 0
    n = len(text)
    out: list[str] = []
    while i < n:
        node = trie
        best_end = -1
        j = i
        while j < n and j - i < max_len:
            ch = text[j]
            if ch not in node:
                break
            node = node[ch]
            j += 1
            if "$" in node:
                best_end = j
        if best_end < 0:
            # single char fallback if in dict as 1-char
            ch = text[i]
            if ch in trie and "$" in trie[ch]:
                out.append(ch)
                i += 1
                continue
            return None  # stuck
        out.append(text[i:best_end])
        i = best_end
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, required=True)
    ap.add_argument("--corpus", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--max-lines", type=int, default=0)
    ap.add_argument("--ctx-chars", type=int, default=16)
    ap.add_argument("--ambig-gap", type=float, default=0.5,
                    help="min score gap for multi-reading words")
    ap.add_argument("--min-word-len", type=int, default=1)
    args = ap.parse_args()

    print(f"loading dict {args.data}", flush=True)
    r2w, w2r = load_dict(args.data)
    words = list(w2r.keys())
    trie = build_trie(words)
    print(f"dict_words={len(words)} readings={len(r2w)}", flush=True)

    drop = Counter()
    pairs = 0
    lines_in = 0
    lines_kept = 0
    lines_mainland = 0
    lines_seg_fail = 0
    han_chars = 0

    out_f = args.out.open("w", encoding="utf-8")
    # format: left_context \t reading \t word
    with args.corpus.open(encoding="utf-8", errors="ignore") as f:
        for line in f:
            if args.max_lines and lines_in >= args.max_lines:
                break
            lines_in += 1
            line = line.strip()
            if not line:
                drop["empty_line"] += 1
                continue
            if any(m in line for m in MAINLAND_MARKERS):
                lines_mainland += 1
                drop["mainland_line"] += 1
                continue
            # extract han runs as separate segments
            runs = HAN_RE.findall(line)
            if not runs:
                drop["no_han"] += 1
                continue
            line_ok = False
            for run in runs:
                if len(run) < 2:
                    drop["short_run"] += 1
                    continue
                segs = longest_match_segment(run, trie)
                if segs is None:
                    lines_seg_fail += 1
                    drop["seg_fail"] += 1
                    continue
                # build pairs
                left_full = ""
                for w in segs:
                    if len(w) < args.min_word_len:
                        drop["short_word"] += 1
                        left_full += w
                        continue
                    rd, reason = best_reading(w, w2r, args.ambig_gap)
                    if rd is None:
                        drop[reason or "no_reading"] += 1
                        left_full += w
                        continue
                    # left context: last ctx_chars of previous text in run
                    left = left_full[-args.ctx_chars :]
                    # skip if no left context (sentence start still ok with empty)
                    out_f.write(f"{left}\t{rd}\t{w}\n")
                    pairs += 1
                    han_chars += len(w)
                    left_full += w
                    line_ok = True
            if line_ok:
                lines_kept += 1

    out_f.close()
    print(f"lines_in={lines_in}", flush=True)
    print(f"lines_kept={lines_kept}", flush=True)
    print(f"lines_mainland_dropped={lines_mainland}", flush=True)
    print(f"pairs={pairs}", flush=True)
    print(f"han_chars_in_targets≈{han_chars}", flush=True)
    print("drop_reasons:", flush=True)
    for k, v in drop.most_common():
        print(f"  {k}={v}", flush=True)
    print(f"wrote {args.out}", flush=True)
    return 0 if pairs > 1000 else 1


if __name__ == "__main__":
    sys.exit(main())
