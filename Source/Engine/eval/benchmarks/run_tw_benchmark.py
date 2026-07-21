#!/usr/bin/env python3
"""
Taiwan Typing Benchmark (北極星指標)
Run this after building or with the C++ harness.

For now, this is a python driver that can call the C++ tw_benchmark or implement simple.

For prototype, it loads the tsv and prints the cases for manual or future integration.

Usage: python run_tw_benchmark.py tw-sentences.tsv
"""

import sys
import subprocess

def main():
    if len(sys.argv) < 2:
        print("Usage: python run_tw_benchmark.py tw-sentences.tsv [lm-data]")
        sys.exit(1)

    tsv = sys.argv[1]
    with open(tsv) as f:
        cases = [line.strip().split('\t') for line in f if line.strip() and not line.startswith('#')]

    print(f"Loaded {len(cases)} Taiwan benchmark sentences.")

    # TODO: call the C++ binary or implement via the grid
    # For now, print first few
    for r, e in cases[:5]:
        print(f"  {r} -> {e}")

    print("\nRun the C++ tw_benchmark or integrate with rerank_eval for real numbers.")
    print("This is the north star for EM / bigram changes.")

if __name__ == "__main__":
    main()
