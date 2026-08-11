#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build MAIN_SCALE by deduping validation JSONL against FP_train.

FP_train = union of training text that fed shipping-path models.
Default sources (this tree, 2026-08):
  - v2c spoken: ~/laowang-data/ptt_spoken_train_v2.txt
  - v2d contrastive: EX1166 在/再 train sentences (exported)

Wiki: v2c meta says wiki=None — not merged. If a wiki path is passed and exists,
it is merged; if --require-wiki and missing → WIKI_FP_MISSING.

CONFIG: ngram=8 (exact + n-gram filter). Normalization: strip all whitespace.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path


def norm(s: str) -> str:
    return "".join(s.split())


def grams(s: str, n: int = 8) -> set[str]:
    if not s:
        return set()
    if len(s) < n:
        return {s}
    return {s[i : i + n] for i in range(len(s) - n + 1)}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_train_lines(paths: list[Path]) -> list[str]:
    lines: list[str] = []
    for p in paths:
        with p.open(encoding="utf-8", errors="replace") as f:
            for line in f:
                t = norm(line.strip())
                if t:
                    lines.append(t)
    return lines


def load_items(path: Path) -> list[dict]:
    items = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                items.append(json.loads(line))
    return items


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--x",
        type=Path,
        default=Path.home()
        / "Documents/i注音-語料/EX1166-題庫/X驗證集-真實語料.jsonl",
    )
    ap.add_argument(
        "--ptt",
        type=Path,
        default=Path.home()
        / "Documents/i注音-語料/EX1166-題庫/自然驗證集-真實語料.jsonl",
    )
    ap.add_argument(
        "--fp",
        type=Path,
        action="append",
        default=None,
        help="FP_train text file (repeatable). Default: PTT spoken + v2d zaizai.",
    )
    ap.add_argument(
        "--wiki",
        type=Path,
        default=None,
        help="Optional wiki text; merged only if path exists.",
    )
    ap.add_argument(
        "--require-wiki",
        action="store_true",
        help="If set and wiki missing → WIKI_FP_MISSING=true, MAIN conditional.",
    )
    ap.add_argument("--ngram", type=int, default=8)
    ap.add_argument(
        "--out-dir",
        type=Path,
        default=Path.home() / "laowang-data/main-scale",
    )
    args = ap.parse_args()
    ngram = args.ngram

    default_fp = [
        Path.home() / "laowang-data/ptt_spoken_train_v2.txt",
        Path.home() / "laowang-data/fp-train-v2d-zaizai-sentences.txt",
    ]
    fp_paths = list(args.fp) if args.fp else default_fp

    wiki_fp_missing = False
    wiki_merged = False
    if args.wiki is not None:
        if args.wiki.exists():
            fp_paths.append(args.wiki)
            wiki_merged = True
        else:
            wiki_fp_missing = True
    elif args.require_wiki:
        wiki_fp_missing = True

    # v2c shipping meta: wiki=None → not in training; no require by default
    missing = [p for p in fp_paths if not p.exists()]
    if missing:
        print("FATAL missing FP files:", file=sys.stderr)
        for p in missing:
            print(f"  {p}", file=sys.stderr)
        return 2

    print("=== FP_train sources ===")
    manifest = []
    for p in fp_paths:
        digest = sha256_file(p)
        size = p.stat().st_size
        print(f"path={p} bytes={size} sha256={digest}")
        manifest.append({"path": str(p), "bytes": size, "sha256": digest})

    print(f"CONFIG ngram={ngram}")
    print(f"WIKI_MERGED={wiki_merged}")
    print(f"WIKI_FP_MISSING={wiki_fp_missing}")

    print("loading FP_train …", flush=True)
    train_lines = load_train_lines(fp_paths)
    train_exact = set(train_lines)
    print(f"fp_lines={len(train_lines)} fp_unique_exact={len(train_exact)}", flush=True)

    sources = {"X": args.x, "PTT": args.ptt}
    val: dict[str, list[dict]] = {}
    for name, path in sources.items():
        val[name] = load_items(path)

    # val 8-grams → (source, idx)
    g2hits: dict[str, set[tuple[str, int]]] = defaultdict(set)
    for name, items in val.items():
        for i, o in enumerate(items):
            s = norm(o["sentence"])
            for g in grams(s, ngram):
                g2hits[g].add((name, i))
    print(f"val_unique_{ngram}grams={len(g2hits)}", flush=True)

    present: set[str] = set()
    for t in train_lines:
        for g in grams(t, ngram):
            if g in g2hits:
                present.add(g)
    print(f"hit_val_{ngram}grams={len(present)}", flush=True)

    kept_items: list[dict] = []
    print("source\traw\texact_removed\tngram_removed\tfinal")
    for name, items in val.items():
        exact_idx = set()
        ngram_idx = set()
        for i, o in enumerate(items):
            s = norm(o["sentence"])
            if s in train_exact:
                exact_idx.add(i)
                continue
            if any(g in present for g in grams(s, ngram)):
                ngram_idx.add(i)
        raw = len(items)
        er, nr = len(exact_idx), len(ngram_idx)
        final = raw - er - nr
        print(f"{name}\t{raw}\t{er}\t{nr}\t{final}")
        for i, o in enumerate(items):
            if i in exact_idx or i in ngram_idx:
                continue
            row = dict(o)
            row["main_scale_source"] = name
            kept_items.append(row)

    total = len(kept_items)
    print(f"MAIN_SCALE_final_total\t{total}")

    if wiki_fp_missing:
        main_ok = "conditional"
    else:
        main_ok = "full"
    print(f"MAIN_SCALE_OK={main_ok}")

    out_dir: Path = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    main_path = out_dir / "MAIN_SCALE.jsonl"
    with main_path.open("w", encoding="utf-8") as f:
        for o in kept_items:
            f.write(json.dumps(o, ensure_ascii=False) + "\n")
    main_sha = sha256_file(main_path)
    print(f"wrote {main_path} sha256={main_sha} items={total}")

    man_path = out_dir / "fp-train-manifest.json"
    man = {
        "sources": manifest,
        "ngram": ngram,
        "WIKI_MERGED": wiki_merged,
        "WIKI_FP_MISSING": wiki_fp_missing,
        "MAIN_SCALE_OK": main_ok,
        "MAIN_SCALE_path": str(main_path),
        "MAIN_SCALE_sha256": main_sha,
        "MAIN_SCALE_final_total": total,
        "v2c_meta_wiki": "None (path-char-lstm-spoken-v2c.meta.txt)",
    }
    man_path.write_text(json.dumps(man, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {man_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
