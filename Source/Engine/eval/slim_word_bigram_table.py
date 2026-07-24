#!/usr/bin/env python3
"""Post-filter a shipped word-bigram PMI TSV by |PMI| threshold.

The build pipeline already supports --min-abs-pmi, but regenerating from a
Wikipedia dump is slow. This tool filters an existing TSV so harness can
compare size vs north-star accuracy without re-segmentation.

Usage:
 slim_word_bigram_table.py \\
 --in ../../Data/word-bigrams.tsv \\
 --out /tmp/word-bigrams-abs2.0.tsv \\
 --min-abs-pmi 2.0

Then:
 cd benchmarks && ./build-and-run.sh tw538-northstar.tsv /tmp/word-bigrams-abs2.0.tsv 0.75
"""

from __future__ import annotations

import argparse
from pathlib import Path


def main() -> int:
 ap = argparse.ArgumentParser(description=__doc__)
 ap.add_argument("--in", dest="inp", type=Path, required=True)
 ap.add_argument("--out", type=Path, required=True)
 ap.add_argument("--min-abs-pmi", type=float, required=True)
 args = ap.parse_args()

 thr = args.min_abs_pmi
 kept = 0
 total = 0
 headers: list[str] = []
 body: list[str] = []

 with args.inp.open("r", encoding="utf-8") as handle:
 for line in handle:
 if line.startswith("#"):
 headers.append(line)
 continue
 if not line.strip():
 continue
 parts = line.rstrip("\n").split("\t")
 if len(parts) < 3:
 continue
 total += 1
 try:
 pmi = float(parts[2])
 except ValueError:
 continue
 if abs(pmi) >= thr:
 body.append(line if line.endswith("\n") else line + "\n")
 kept += 1

 args.out.parent.mkdir(parents=True, exist_ok=True)
 with args.out.open("w", encoding="utf-8") as out:
 for h in headers:
 if "min_abs_pmi=" in h:
 h = h.rstrip("\n")
 # Annotate rather than invent a full rebuild header.
 if "post-filter" not in h:
 h = h + f" post-filter_min_abs_pmi={thr}"
 out.write(h + "\n")
 else:
 out.write(h if h.endswith("\n") else h + "\n")
 out.write(
 f"# slim_word_bigram_table.py: kept |pmi|>={thr} "
 f"({kept}/{total} rows)\n"
 )
 for line in body:
 out.write(line)

 size_mb = args.out.stat().st_size / (1024 * 1024)
 print(f"wrote {args.out}")
 print(f"rows {kept}/{total} ({100.0 * kept / max(total, 1):.1f}%)")
 print(f"size {size_mb:.2f} MB")
 return 0


if __name__ == "__main__":
 raise SystemExit(main())
