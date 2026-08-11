#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""floor_pass.py — FLOOR noise-floor gate (Johnny baton-1 / §FLOOR).

Compares baseline dump vs after dump (newstar dump.tsv format).

Definitions (locked):
  b = baseline correct → after wrong   (regression)
  c = baseline wrong   → after correct (fix)
  n = b + c
  p = P(X ≥ c | X ~ Binomial(n, 0.5))   # one-sided exact
  FLOOR_PASS ⇔ (c − b > 0) and (p < α)
  α default 0.05 (CONFIG)

Also reports (not gates): MDE_net, SCALE_UNDERPOWERED, SPLIT_HALF_STABILITY.

This is NOT compare_dumps.py (two-sided, inverted b/c labels).
"""

from __future__ import annotations

import argparse
import math
import random
import sys
from typing import Dict, Optional, Tuple


def load_dump(path: str) -> Dict[str, int]:
    """sentence_id → correct (0/1). newstar dump: header + tab fields."""
    rows: Dict[str, int] = {}
    with open(path, encoding="utf-8") as fh:
        header = fh.readline()
        if not header:
            raise SystemExit(f"{path}: empty")
        # tolerate missing header name
        for line in fh:
            if not line.strip():
                continue
            f = line.rstrip("\n").split("\t")
            if len(f) < 4:
                continue
            # columns: sentence_id, pair_id, split, correct, ...
            sid, correct = f[0], f[3]
            if sid == "sentence_id":
                continue
            rows[sid] = int(correct)
    return rows


def binom_sf_ge(c: int, n: int) -> float:
    """P(X >= c) for X~Binom(n, 0.5), exact."""
    if n == 0:
        return 1.0
    if c <= 0:
        return 1.0
    if c > n:
        return 0.0
    # sum_{i=c}^n C(n,i) / 2^n
    total = 0.0
    # iterative C(n,k)
    term = 1.0  # C(n,0)
    for k in range(0, n + 1):
        if k >= c:
            total += term
        if k < n:
            term *= (n - k) / (k + 1)
    return total / (2.0**n)


def classify(base: Dict[str, int], after: Dict[str, int]) -> Tuple[int, int, int]:
    common = set(base) & set(after)
    b = c = 0
    for sid in common:
        bb, aa = base[sid], after[sid]
        if bb == 1 and aa == 0:
            b += 1
        elif bb == 0 and aa == 1:
            c += 1
    return b, c, b + c


def floor_pass(b: int, c: int, alpha: float = 0.05) -> Tuple[float, bool]:
    n = b + c
    p = binom_sf_ge(c, n)
    ok = (c - b > 0) and (p < alpha)
    return p, ok


def mde_net_power(pi: float = 0.6, alpha: float = 0.05, power: float = 0.8) -> Tuple[int, float]:
    """Approx n_disc and expected net for one-sided z-test H0 p=0.5 vs p=pi."""
    if pi <= 0.5:
        return 0, 0.0
    za = 1.64485  # one-sided 0.05
    zb = 0.84162  # power 0.8
    d = pi - 0.5
    n = math.ceil(((za * 0.5 + zb * math.sqrt(pi * (1 - pi))) / d) ** 2)
    return n, n * (2 * pi - 1)


def split_half_stability(
    base: Dict[str, int],
    after: Dict[str, int],
    seed: int = 0,
    alpha: float = 0.05,
) -> str:
    common = sorted(set(base) & set(after))
    if len(common) < 4:
        return "NA_too_few"
    rng = random.Random(seed)
    rng.shuffle(common)
    mid = len(common) // 2
    halves = [common[:mid], common[mid:]]
    nets = []
    passes = []
    for half in halves:
        b = c = 0
        for sid in half:
            bb, aa = base[sid], after[sid]
            if bb == 1 and aa == 0:
                b += 1
            elif bb == 0 and aa == 1:
                c += 1
        p, ok = floor_pass(b, c, alpha)
        nets.append(c - b)
        passes.append(ok)
    sign_agree = (nets[0] > 0) == (nets[1] > 0) if (nets[0] != 0 or nets[1] != 0) else True
    return (
        f"net_half=({nets[0]},{nets[1]}) "
        f"FLOOR_PASS_half=({passes[0]},{passes[1]}) "
        f"sign_agree={sign_agree}"
    )


def print_block(
    b: int,
    c: int,
    alpha: float,
    n_main: Optional[int],
    base: Optional[Dict[str, int]] = None,
    after: Optional[Dict[str, int]] = None,
    seed: int = 0,
) -> None:
    n = b + c
    p, ok = floor_pass(b, c, alpha)
    print(f"b={b}")
    print(f"c={c}")
    print(f"n={n}")
    print(f"p={p}")
    print(f"α={alpha}")
    print(f"FLOOR_PASS={ok}")

    n_need, mde = mde_net_power(0.6, alpha, 0.8)
    print(f"MDE_net={mde:.4f}")  # expected net at π=0.6 power 0.8
    print(f"MDE_n_disc_for_pi0.6={n_need}")
    under = n < n_need
    if n_main is not None:
        # also flag if scale is small relative to MDE needs for mild effects
        print(f"N_main={n_main}")
    print(f"SCALE_UNDERPOWERED={under}")
    if under:
        print(f"min_n_disc_for_power0.8_pi0.6={n_need}")

    if base is not None and after is not None:
        print(f"SPLIT_HALF_STABILITY={split_half_stability(base, after, seed, alpha)}")
    else:
        print("SPLIT_HALF_STABILITY=NA")


def run_selftests(alpha: float = 0.05) -> int:
    print("=== floor_pass selftests ===")
    # t1
    print("--- t1 b=0 c=0 ---")
    print_block(0, 0, alpha, n_main=None)
    p1, ok1 = floor_pass(0, 0, alpha)
    assert ok1 is False, "t1 must FAIL"
    print("t1_assert_FLOOR_PASS_False=OK")

    # t2 n=10 c=9 b=1 → net=8
    print("--- t2 n=10 c=9 b=1 ---")
    print_block(1, 9, alpha, n_main=None)
    p2, ok2 = floor_pass(1, 9, alpha)
    print(f"t2_expected_note p={p2} FLOOR_PASS={ok2}")
    # P(X>=9|n=10,0.5)=11/1024≈0.0107 < 0.05 and net>0 → True
    assert ok2 is True, "t2 should PASS"
    print("t2_assert_FLOOR_PASS_True=OK")

    # t3 large n, tiny but significant net
    # For n=100, need c such that p<0.05 and c>50. min c≈59 → b=41 c=59 net=18
    # For "tiny": use n=10000, net just above threshold ~ 1.645*sqrt(n) ≈ 165
    # Smaller demo: n=200, min net ~26 from baton0 — use b=87 c=113 net=26
    print("--- t3 large n small net (significant) ---")
    b3, c3 = 87, 113  # n=200 net=26
    print_block(b3, c3, alpha, n_main=3395)
    p3, ok3 = floor_pass(b3, c3, alpha)
    assert ok3 is True, "t3 should PASS statistically"
    print(
        f"t3_demo FLOOR_PASS={ok3} net={c3-b3} "
        f"(statistically true; product impact may feel small vs N_main)"
    )
    print("t3_assert_FLOOR_PASS_True=OK")
    print("=== selftests DONE ===")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("baseline", nargs="?", help="baseline dump.tsv")
    ap.add_argument("after", nargs="?", help="after dump.tsv")
    ap.add_argument("--alpha", type=float, default=0.05)
    ap.add_argument("--n-main", type=int, default=None, help="MAIN scale size for context")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        return run_selftests(args.alpha)

    if not args.baseline or not args.after:
        ap.error("baseline and after dumps required (or --selftest)")

    base = load_dump(args.baseline)
    after = load_dump(args.after)
    b, c, n = classify(base, after)
    print_block(b, c, args.alpha, args.n_main, base, after, args.seed)
    print(f"common_items={len(set(base)&set(after))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
