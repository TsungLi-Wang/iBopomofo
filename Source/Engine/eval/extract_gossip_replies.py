#!/usr/bin/env python3
"""Extract PTT Gossiping push-reply Content lines from zake7749 source_replies.

Input: a directory of reply/N.json files (from
  Gossiping-Chinese-Corpus/data/source_replies/reply.7z), each a JSON list of
  articles; each article is a list of push objects {"Vote","Content","User"}.

Output: one push Content per line (--out), the plain-text feed consumed by
  build_spoken_corpus.py --extra-txt (stem must be 'replies_pushes_only' to
  reproduce the src_replies_pushes_only stat tag). No filtering here — all
  cleaning/dedup/PRC drops happen downstream in build_spoken_corpus.py, so the
  extracted set is order-independent for the han metric.

Deterministic: files processed in numeric filename order.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


def numeric_key(p: Path) -> int:
    m = re.match(r"(\d+)", p.stem)
    return int(m.group(1)) if m else 1 << 30


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reply-dir", type=Path, required=True,
                    help="dir containing N.json reply files")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    files = sorted(args.reply_dir.glob("*.json"), key=numeric_key)
    if not files:
        print(f"no json under {args.reply_dir}", file=sys.stderr)
        return 1

    pushes = 0
    articles = 0
    bad = 0
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as w:
        for fp in files:
            try:
                data = json.load(fp.open(encoding="utf-8", errors="ignore"))
            except json.JSONDecodeError:
                bad += 1
                continue
            for article in data:
                articles += 1
                if not isinstance(article, list):
                    continue
                for push in article:
                    if not isinstance(push, dict):
                        continue
                    content = push.get("Content")
                    if not content:
                        continue
                    # newlines would split a line downstream; flatten to space
                    content = content.replace("\r", " ").replace("\n", " ")
                    w.write(content + "\n")
                    pushes += 1

    print(f"files={len(files)} articles={articles} pushes={pushes} bad_json={bad}",
          flush=True)
    print(f"wrote {args.out}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
