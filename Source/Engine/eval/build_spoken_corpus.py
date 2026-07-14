#!/usr/bin/env python3
"""Build pollution-safe spoken PTT training corpus for char-LSTM.

Pollution ban (must NOT appear as source boards):
  Stock, PC_Shopping, Tech_Job, WomenTalk, movie, Food, Lifeismoney,
  Soft_Job, MobileComm, car, C_Chat

Allowed primary: Gossiping (+ other non-banned boards if provided).

Cleaning (same spirit as spoken A/B bar):
  - drop empty / 沒有資料
  - drop lines with PRC lexical markers
  - strip URLs
  - dedupe exact lines
  - keep Traditional-leaning text (drop high simplified-marker density)

Usage:
  python3 build_spoken_corpus.py \\
    --qa-csv /tmp/ptt-gossip-expand/Gossiping-QA-Dataset-2_0.csv \\
    --qa-txt /tmp/ptt-gossip/Gossiping-QA-Dataset.txt \\
    --extra-jsonl /tmp/ptt-gossip-expand/extra_boards.jsonl \\
    --out /tmp/ptt-gossip-expand/ptt_spoken_train_v2.txt \\
    --stats /tmp/ptt-gossip-expand/corpus_stats.json
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

BANNED_BOARDS = {
    "Stock",
    "PC_Shopping",
    "Tech_Job",
    "WomenTalk",
    "movie",
    "Food",
    "Lifeismoney",
    "Soft_Job",
    "MobileComm",
    "car",
    "C_Chat",
    "stock",
    "c_chat",
}

URL_RE = re.compile(r"https?://\S+|www\.\S+", re.I)

# PRC / simplified leakage markers (line-level drop if hit)
PRC_MARKERS = [
    "视频",
    "软件",
    "质量",
    "网络",
    "默认",
    "信息",
    "粉丝",
    "给力",
    "卧槽",
    "牛逼",
    "装逼",
    "傻逼",
    "咋整",
    "咋办",
    "啥意思",
    "有木有",
    "肿么",
    "酱紫",
    "内牛满面",
    "三国杀",  # often CN game spam in old dumps; keep mild
]

# High-confidence simplified chars rarely used in TW traditional
SIMP_CHARS = set("国来对会这说时样经现过还发长学点动同样从无开问们")


def clean_text(s: str) -> str:
    s = URL_RE.sub(" ", s)
    s = s.replace("\u3000", " ")
    s = re.sub(r"[ \t\f\v]+", " ", s)
    s = s.strip()
    return s


def is_prc_or_simp(s: str) -> bool:
    for m in PRC_MARKERS:
        if m in s:
            return True
    # if many simplified-only forms appear densely
    hits = sum(1 for ch in s if ch in SIMP_CHARS)
    if hits >= 4 and hits / max(1, len(s)) > 0.08:
        return True
    return False


def han_count(s: str) -> int:
    return sum(1 for c in s if "\u4e00" <= c <= "\u9fff")


def add_line(line: str, seen: set[str], out: list[str], stats: Counter) -> None:
    line = clean_text(line)
    if not line or line == "沒有資料":
        stats["drop_empty"] += 1
        return
    if han_count(line) < 4:
        stats["drop_short"] += 1
        return
    if is_prc_or_simp(line):
        stats["drop_prc"] += 1
        return
    if line in seen:
        stats["drop_dupe"] += 1
        return
    seen.add(line)
    out.append(line)
    stats["kept"] += 1
    stats["han"] += han_count(line)
    stats["chars"] += len(line)


def load_qa_txt(path: Path, seen: set[str], out: list[str], stats: Counter) -> None:
    if not path or not path.exists():
        return
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if "\t" in raw:
            q, a = raw.split("\t", 1)
            add_line(q + a, seen, out, stats)
        else:
            add_line(raw, seen, out, stats)
        stats["src_qa_txt"] += 1


def load_qa_csv(path: Path, seen: set[str], out: list[str], stats: Counter) -> None:
    if not path or not path.exists():
        return
    with path.open(encoding="utf-8", errors="ignore", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            q = (row.get("question") or "").strip()
            a = (row.get("answer") or "").strip()
            if a == "沒有資料":
                stats["drop_no_data"] += 1
                continue
            add_line(q + a, seen, out, stats)
            stats["src_qa_csv"] += 1


def load_jsonl(path: Path, seen: set[str], out: list[str], stats: Counter) -> None:
    if not path or not path.exists():
        return
    with path.open(encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                stats["drop_bad_json"] += 1
                continue
            board = str(obj.get("board") or obj.get("source_board") or "")
            if board in BANNED_BOARDS:
                stats["drop_banned_board"] += 1
                stats[f"banned_{board}"] += 1
                continue
            body = obj.get("body") or obj.get("text") or ""
            title = obj.get("title") or ""
            text = f"{title}\n{body}" if title else body
            for para in re.split(r"[\n\r]+", text):
                add_line(para, seen, out, stats)
            stats["src_jsonl"] += 1
            if board:
                stats[f"board_{board}"] += 1


def load_plain(path: Path, seen: set[str], out: list[str], stats: Counter,
               source_tag: str) -> None:
    if not path or not path.exists():
        return
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        add_line(raw, seen, out, stats)
        stats[f"src_{source_tag}"] += 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--qa-csv", type=Path, default=None)
    ap.add_argument("--qa-txt", type=Path, default=None)
    ap.add_argument("--extra-jsonl", type=Path, default=None, action="append")
    ap.add_argument("--extra-txt", type=Path, default=None, action="append")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--stats", type=Path, default=None)
    args = ap.parse_args()

    seen: set[str] = set()
    out: list[str] = []
    stats: Counter = Counter()

    if args.qa_txt:
        load_qa_txt(args.qa_txt, seen, out, stats)
    if args.qa_csv:
        load_qa_csv(args.qa_csv, seen, out, stats)
    for p in args.extra_jsonl or []:
        load_jsonl(p, seen, out, stats)
    for p in args.extra_txt or []:
        load_plain(p, seen, out, stats, p.stem)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(out) + ("\n" if out else ""), encoding="utf-8")

    report = {
        "out": str(args.out),
        "lines": len(out),
        "han_chars": stats["han"],
        "chars": stats["chars"],
        "bytes": args.out.stat().st_size,
        "counts": dict(stats),
        "banned_boards": sorted(BANNED_BOARDS),
        "sources": {
            "qa_csv": str(args.qa_csv) if args.qa_csv else None,
            "qa_txt": str(args.qa_txt) if args.qa_txt else None,
            "extra_jsonl": [str(p) for p in (args.extra_jsonl or [])],
            "extra_txt": [str(p) for p in (args.extra_txt or [])],
        },
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.stats:
        args.stats.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                              encoding="utf-8")
    if stats["han"] < 20_000_000:
        print(
            f"WARNING: han_chars={stats['han']} < 20M stop-threshold; "
            f"target was >=40M",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
