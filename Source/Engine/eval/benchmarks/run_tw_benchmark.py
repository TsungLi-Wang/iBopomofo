#!/usr/bin/env python3
"""Driver stub: only loads tw538 (537 sentences)."""
import sys
from pathlib import Path

def main():
    if len(sys.argv) < 2:
        print("Usage: python run_tw_benchmark.py tw538-northstar.tsv")
        sys.exit(1)
    tsv = Path(sys.argv[1])
    if "tw-sentences" in tsv.name:
        print(f"FATAL: retired benchmark corpus refused: {tsv}", file=sys.stderr)
        sys.exit(3)
    cases = []
    for line in tsv.read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        if "\t" in line or "	" in line:
            cases.append(line)
    if len(cases) != 537:
        print(f"FATAL: benchmark gate: expected 537 sentences, got {len(cases)}", file=sys.stderr)
        sys.exit(3)
    print(f"Loaded {len(cases)} tw538 sentences (gate OK).")

if __name__ == "__main__":
    main()
