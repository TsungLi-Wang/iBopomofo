#!/usr/bin/env python3
"""Baton A-2: flip gate sweep + diagnostics (pure analysis).

Reads baton-A assets + flip_proposal_dump outputs. Does not retrain or touch app.

Example:
  python3 Source/Engine/eval/tools/analyze_flip_gates.py \\
    --repo ~/iBopomofo \\
    --data-dir ~/laowang-data \\
    --dump-dir ~/laowang-data/batonA2-gate-dump
"""
from __future__ import annotations

import argparse
import hashlib
import math
import random
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(8 * 1024 * 1024)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def load_tsv(path: Path) -> tuple[list[str], list[dict]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines:
        return [], []
    header = lines[0].split("\t")
    rows = []
    for line in lines[1:]:
        if not line.strip():
            continue
        parts = line.split("\t")
        row = {}
        for i, k in enumerate(header):
            row[k] = parts[i] if i < len(parts) else ""
        rows.append(row)
    return header, rows


def fnum(x: str) -> float:
    return float(x)


def inum(x: str) -> int:
    return int(x)


@dataclass
class Proposal:
    sent: int
    pos: int
    frm: str
    to: str
    delta: float
    score_s: float
    score_sp: float
    ship_correct: bool
    after_correct: bool
    gold_in_pool: bool
    pred: str
    gold: str
    H: float
    gold_rank: int
    M: int
    error_class: str  # A / B / OK


def build_proposals(
    prop_rows: list[dict], ent_by_sp: dict[tuple[int, int], dict], ship: dict[int, dict]
) -> list[Proposal]:
    out: list[Proposal] = []
    for r in prop_rows:
        si = inum(r["sent_idx"])
        pos = inum(r["pos"])
        e = ent_by_sp.get((si, pos), {})
        H = fnum(e["H_bits"]) if e else float("nan")
        gr = inum(e["gold_rank"]) if e and e.get("gold_rank", "") not in ("", "-1") else -1
        M = inum(e["|C|"]) if e and e.get("|C|") else 0
        ship_ok = r["ship_correct"] == "1"
        gip = r["gold_in_pool"] == "1"
        if ship_ok:
            ec = "OK"
        else:
            ec = "A" if gip else "B"
        out.append(
            Proposal(
                sent=si,
                pos=pos,
                frm=r["from"],
                to=r["to"],
                delta=fnum(r["delta_v2c"]),
                score_s=fnum(r["score_S"]),
                score_sp=fnum(r["score_Sp"]),
                ship_correct=ship_ok,
                after_correct=r["after_correct"] == "1",
                gold_in_pool=gip,
                pred=r["pred"],
                gold=r["gold"],
                H=H,
                gold_rank=gr,
                M=M,
                error_class=ec,
            )
        )
    return out


def apply_single_best(
    props: list[Proposal],
    ship: dict[int, dict],
    delta_min: float,
    h_min: float | None,
    h_max: float | None,
    allow_pos: set[tuple[int, int]] | None = None,
    score_key: str = "delta",
) -> dict:
    """Per sentence: among proposals passing gates, take max score_key; apply 1 flip.

    Returns sentence-level and position-level stats.
    """
    by_sent: dict[int, list[Proposal]] = defaultdict(list)
    for p in props:
        by_sent[p.sent].append(p)

    n_sent = len(ship)
    ship_correct = sum(1 for s in ship.values() if s["correct"] == "1")
    rescue = regress = neutral_flip = 0
    rescue_a = rescue_b = regress_a = regress_b = 0
    accepted = 0
    pos_fix = pos_break = 0  # position-level: wrong→right / right→wrong for the flipped pos
    # position accuracy after: start from shipping pos correctness
    # We only change one position per sentence when accepted.

    for si, srow in ship.items():
        was = srow["correct"] == "1"
        gip = srow["gold_in_pool"] == "1"
        cands = []
        for p in by_sent.get(si, []):
            if p.delta < delta_min:
                continue
            if h_min is not None and not (p.H >= h_min):
                continue
            if h_max is not None and not (p.H <= h_max):
                continue
            if allow_pos is not None and (p.sent, p.pos) not in allow_pos:
                continue
            cands.append(p)
        if not cands:
            continue
        best = max(cands, key=lambda p: p.delta if score_key == "delta" else p.score_sp)
        # Require score improvement; delta_min is additional margin (≥0).
        if best.delta <= 0:
            continue
        if best.delta < delta_min:
            continue
        accepted += 1
        now = best.after_correct
        # position-level: did this position go wrong→right or right→wrong?
        # shipping pred char at pos vs gold
        # after_correct is sentence-level. For position: compare from/to to gold char at pos.
        ent = None  # filled by caller if needed
        # Approximate pos fix: if best.to equals the gold char at that position from entropy
        # We don't have gold char here on Proposal — use after_correct + ship for sentence only
        # Position: if shipping was wrong at pos and to==gold → fix; if was right and to!=gold → break
        # gold char from entropy table attached earlier? Use proposal: we can check after_correct
        # for single-error sentences after_correct implies pos fix; multi-error not necessarily.
        # Better: compare `to` with gold string at pos if lengths match.
        gold_chars = list(best.gold)
        pred_chars = list(best.pred)
        if best.pos < len(gold_chars) and best.pos < len(pred_chars):
            was_pos_ok = pred_chars[best.pos] == gold_chars[best.pos]
            now_pos_ok = best.to == gold_chars[best.pos]
            if not was_pos_ok and now_pos_ok:
                pos_fix += 1
            elif was_pos_ok and not now_pos_ok:
                pos_break += 1

        if not was and now:
            rescue += 1
            if gip:
                rescue_a += 1
            else:
                rescue_b += 1
        elif was and not now:
            regress += 1
            if gip:
                regress_a += 1
            else:
                regress_b += 1
        else:
            neutral_flip += 1

    final_correct = ship_correct + rescue - regress
    return {
        "delta_min": delta_min,
        "h_min": h_min,
        "h_max": h_max,
        "accepted": accepted,
        "pos_fix": pos_fix,
        "pos_break": pos_break,
        "rescue": rescue,
        "regress": regress,
        "rescue_a": rescue_a,
        "rescue_b": rescue_b,
        "regress_a": regress_a,
        "regress_b": regress_b,
        "neutral_flip": neutral_flip,
        "ship_correct": ship_correct,
        "final_correct": final_correct,
        "net": final_correct - ship_correct,
        "n_sent": n_sent,
    }


def apply_v4_nbest(
    nbest_rows: list[dict],
    ship: dict[int, dict],
    ent_by_sp: dict[tuple[int, int], dict],
    delta_min: float,
    h_min: float | None,
    h_max: float | None,
) -> dict:
    """Pick best fused path (walk + 0.75*v2c) among nbest if gates pass on differing positions."""
    by_sent: dict[int, list[dict]] = defaultdict(list)
    for r in nbest_rows:
        by_sent[inum(r["sent_idx"])].append(r)

    ship_correct = sum(1 for s in ship.values() if s["correct"] == "1")
    rescue = regress = accepted = 0
    rescue_a = rescue_b = regress_a = regress_b = 0
    pos_fix = pos_break = 0

    for si, srow in ship.items():
        was = srow["correct"] == "1"
        gip = srow["gold_in_pool"] == "1"
        pred = srow["pred"]
        gold = srow["gold"]
        paths = by_sent.get(si, [])
        if not paths:
            continue
        # shipping fused score
        ship_paths = [p for p in paths if p["is_shipping"] == "1"]
        if ship_paths:
            base = fnum(ship_paths[0]["fused_075"])
        else:
            # fallback: max is_shipping missing — use pred text match
            base = None
            for p in paths:
                if p["text"] == pred:
                    base = fnum(p["fused_075"])
                    break
            if base is None:
                base = fnum(paths[0]["fused_075"])

        best = None
        best_fused = base
        for p in paths:
            if p["text"] == pred:
                continue
            fused = fnum(p["fused_075"])
            delta = fused - base
            if delta < delta_min:
                continue
            # H gate: require ALL differing positions (or max H among them) pass
            # Use max H among positions where chars differ
            t = p["text"]
            pc, tc = list(pred), list(t)
            n = min(len(pc), len(tc))
            Hs = []
            for i in range(n):
                if pc[i] != tc[i]:
                    e = ent_by_sp.get((si, i))
                    if e:
                        Hs.append(fnum(e["H_bits"]))
            if not Hs:
                # length mismatch only
                Hmax = 0.0
            else:
                Hmax = max(Hs)
            if h_min is not None and Hmax < h_min:
                continue
            if h_max is not None and Hmax > h_max:
                continue
            if fused > best_fused:
                best_fused = fused
                best = p

        if best is None:
            continue
        accepted += 1
        now = best["is_gold"] == "1"
        # position stats for differing positions
        t = best["text"]
        pc, tc, gc = list(pred), list(t), list(gold)
        n = min(len(pc), len(tc), len(gc))
        for i in range(n):
            if pc[i] != tc[i]:
                was_ok = pc[i] == gc[i]
                now_ok = tc[i] == gc[i]
                if not was_ok and now_ok:
                    pos_fix += 1
                elif was_ok and not now_ok:
                    pos_break += 1
        if not was and now:
            rescue += 1
            if gip:
                rescue_a += 1
            else:
                rescue_b += 1
        elif was and not now:
            regress += 1
            if gip:
                regress_a += 1
            else:
                regress_b += 1

    final_correct = ship_correct + rescue - regress
    return {
        "delta_min": delta_min,
        "h_min": h_min,
        "h_max": h_max,
        "accepted": accepted,
        "pos_fix": pos_fix,
        "pos_break": pos_break,
        "rescue": rescue,
        "regress": regress,
        "rescue_a": rescue_a,
        "rescue_b": rescue_b,
        "regress_a": regress_a,
        "regress_b": regress_b,
        "ship_correct": ship_correct,
        "final_correct": final_correct,
        "net": final_correct - ship_correct,
        "n_sent": len(ship),
    }


def grid_values() -> tuple[list[float], list[float]]:
    """Delta thresholds and H thresholds.

    Δscore: shipping score is log10 sum ~ -20..-60; typical improving deltas 0.01..3.
    Include 0 (any improvement) and positive margins.
    H: residual entropy bits; wrong median ~1.07; use 0, 0.25, 0.5, 1.0, 1.5, 2.0
    """
    deltas = [0.0, 0.05, 0.1, 0.2, 0.5, 1.0, 1.5, 2.0, 3.0]
    hs = [0.0, 0.1, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0]
    return deltas, hs


def split_half_validate(
    props: list[Proposal],
    ship: dict[int, dict],
    nbest_rows: list[dict] | None,
    ent_by_sp: dict,
    mode: str,
    n_rep: int = 20,
    seed: int = 42,
    allow_pos: set[tuple[int, int]] | None = None,
) -> dict:
    """Pick best gate on half A, evaluate on half B. mode: v2c | v2c_h | v4 | v5."""
    deltas, hs = grid_values()
    sent_ids = sorted(ship.keys())
    wins = 0
    b_nets = []
    a_nets = []
    rng = random.Random(seed)

    for rep in range(n_rep):
        ids = sent_ids[:]
        rng.shuffle(ids)
        mid = len(ids) // 2
        A, B = set(ids[:mid]), set(ids[mid:])
        ship_a = {k: v for k, v in ship.items() if k in A}
        ship_b = {k: v for k, v in ship.items() if k in B}
        props_a = [p for p in props if p.sent in A]
        props_b = [p for p in props if p.sent in B]
        nbest_a = (
            [r for r in nbest_rows if inum(r["sent_idx"]) in A] if nbest_rows else None
        )
        nbest_b = (
            [r for r in nbest_rows if inum(r["sent_idx"]) in B] if nbest_rows else None
        )

        best = None
        best_net = -10**9
        # search grid on A
        if mode == "v2c":
            for d in deltas:
                r = apply_single_best(props_a, ship_a, d, None, None, allow_pos)
                if r["net"] > best_net:
                    best_net = r["net"]
                    best = ("v2c", d, None)
        elif mode == "v2c_h":
            for d in deltas:
                for h in hs:
                    r = apply_single_best(props_a, ship_a, d, h, None, allow_pos)
                    if r["net"] > best_net:
                        best_net = r["net"]
                        best = ("v2c_h", d, h)
        elif mode == "v4":
            for d in deltas:
                for h in hs:
                    r = apply_v4_nbest(nbest_a, ship_a, ent_by_sp, d, h, None)
                    if r["net"] > best_net:
                        best_net = r["net"]
                        best = ("v4", d, h)
        elif mode == "v5":
            for d in deltas:
                for h in hs:
                    r = apply_single_best(props_a, ship_a, d, h, None, allow_pos)
                    if r["net"] > best_net:
                        best_net = r["net"]
                        best = ("v5", d, h)
        else:
            raise ValueError(mode)

        # eval on B
        d_min, h_min = best[1], best[2]
        if mode == "v2c":
            rb = apply_single_best(props_b, ship_b, d_min, None, None, allow_pos)
        elif mode == "v4":
            rb = apply_v4_nbest(nbest_b, ship_b, ent_by_sp, d_min, h_min, None)
        else:
            rb = apply_single_best(props_b, ship_b, d_min, h_min, None, allow_pos)
        a_nets.append(best_net)
        b_nets.append(rb["net"])
        if rb["net"] > 0:
            wins += 1

    return {
        "mode": mode,
        "n_rep": n_rep,
        "win_rate": wins / n_rep,
        "mean_b_net": statistics.mean(b_nets),
        "mean_a_net": statistics.mean(a_nets),
        "b_nets": b_nets,
        "a_nets": a_nets,
        "median_b_net": statistics.median(b_nets),
    }


def fano_bound(H: float, M: float) -> tuple[float, float]:
    """Solve Pe lower bound from Fano: H <= h(Pe) + Pe*log2(M-1).

    Returns (pe_std, pe_weak) where pe_weak = max(0, (H-1)/log2(M)).
    Binary search for standard form.
    """
    if M <= 1:
        return 0.0, 0.0
    log_term = math.log2(M - 1) if M > 1 else 0.0
    # weak
    pe_weak = max(0.0, (H - 1.0) / log_term) if log_term > 0 else 0.0
    pe_weak = min(1.0, pe_weak)

    def rhs(pe: float) -> float:
        if pe <= 0:
            return 0.0
        if pe >= 1:
            return 1.0 + log_term
        h = -pe * math.log2(pe) - (1 - pe) * math.log2(1 - pe)
        return h + pe * log_term

    # if H is tiny, Pe ~ 0
    if H <= 0:
        return 0.0, pe_weak
    lo, hi = 0.0, 1.0
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        if rhs(mid) < H:
            lo = mid
        else:
            hi = mid
    pe_std = min(1.0, hi)
    return pe_std, pe_weak


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", type=Path, default=Path.home() / "iBopomofo")
    ap.add_argument("--data-dir", type=Path, default=Path.home() / "laowang-data")
    ap.add_argument(
        "--dump-dir",
        type=Path,
        default=Path.home() / "laowang-data/batonA2-gate-dump",
    )
    args = ap.parse_args()
    repo: Path = args.repo
    analysis = repo / "Source/Engine/eval/analysis"
    dump: Path = args.dump_dir
    data: Path = args.data_dir
    out_log = data / "batonA2_analysis.stdout.txt"
    log_lines: list[str] = []

    def log(msg: str = "") -> None:
        print(msg, flush=True)
        log_lines.append(msg)

    # --- load ---
    ent_path = analysis / "tw538-residual-entropy.tsv"
    ent_h, ent_rows = load_tsv(ent_path)
    log(f"ENTROPY_HEADER\t{ent_h}")
    log(f"ENTROPY_N\t{len(ent_rows)}")
    log("ENTROPY_PREFIX\tgold (teacher-forced); see homophone_measure.cpp")
    log("ENTROPY_SAMPLE0\t" + "\t".join(ent_rows[0][k] for k in ent_h))
    log("ENTROPY_SAMPLE1\t" + "\t".join(ent_rows[1][k] for k in ent_h))
    log("ENTROPY_SAMPLE2\t" + "\t".join(ent_rows[2][k] for k in ent_h))

    # missing fields
    present = set(ent_h)
    needed = {
        "pred",
        "gold",
        "gold_rank",
        "gold_prob",
        "H_bits",
        "|C|",
        "correct",
        "top1",
        "top1_prob",
        "margin",
        "error_class",
    }
    missing = sorted(needed - present)
    log(f"ENTROPY_MISSING\t{missing}")
    log(
        "ENTROPY_NOTE\ttop1/top1_prob/margin/error_class absent; "
        "error_class derived from shipping gold_in_pool; "
        "top1≈gold when gold_rank==1 else unknown without re-run. "
        "Re-run cost for top1 logits: ~30min (same as residual entropy). "
        "SKIP re-run; use available fields."
    )

    prop_h, prop_rows = load_tsv(dump / "flip_proposals_all.tsv")
    nb_h, nb_rows = load_tsv(dump / "nbest_paths.tsv")
    sh_h, sh_rows = load_tsv(dump / "shipping_preds.tsv")
    ship = {inum(r["sent_idx"]): r for r in sh_rows}
    log(f"PROPOSALS_N\t{len(prop_rows)}")
    log(f"NBEST_N\t{len(nb_rows)}")
    log(f"SHIP_CORRECT\t{sum(1 for r in sh_rows if r['correct']=='1')}/537")

    ent_by_sp = {(inum(r["sent_idx"]), inum(r["pos"])): r for r in ent_rows}
    props = build_proposals(prop_rows, ent_by_sp, ship)
    log(f"PROPOSALS_JOINED\t{len(props)}")
    log(f"PROPOSALS_WITH_H\t{sum(1 for p in props if p.H==p.H)}")

    # V5 allow positions: gold_rank==1 and pred!=gold (shipping wrong at pos)
    allow_v5: set[tuple[int, int]] = set()
    for r in ent_rows:
        if r["correct"] == "0" and r["gold_rank"] == "1":
            allow_v5.add((inum(r["sent_idx"]), inum(r["pos"])))
    log(f"V5_POS_N\t{len(allow_v5)}")

    # --- Step 2 gate sweep V3 surface ---
    deltas, hs = grid_values()
    log(f"GRID_DELTAS\t{deltas}")
    log(f"GRID_H_MIN\t{hs}")
    log(
        "GRID_NOTE\tAccept flip if delta_v2c>=delta_min AND H>=h_min; "
        "per sentence take max-delta proposal among those that pass; "
        "one flip only (round-1 style). h_min gates to high residual entropy positions."
    )

    sweep_path = analysis / "tw538-flip-gate-sweep.tsv"
    with sweep_path.open("w", encoding="utf-8") as fo:
        fo.write(
            "variant\tdelta_min\th_min\taccepted\tpos_fix\tpos_break\t"
            "rescue\tregress\tnet\tfinal_correct\trescue_a\trescue_b\t"
            "regress_a\tregress_b\n"
        )
        # V1: no gate = delta_min=0, no H
        r1 = apply_single_best(props, ship, 0.0, None, None)
        fo.write(
            f"V1\t0\t\t{r1['accepted']}\t{r1['pos_fix']}\t{r1['pos_break']}\t"
            f"{r1['rescue']}\t{r1['regress']}\t{r1['net']}\t{r1['final_correct']}\t"
            f"{r1['rescue_a']}\t{r1['rescue_b']}\t{r1['regress_a']}\t{r1['regress_b']}\n"
        )
        log(
            f"V1\tnet={r1['net']}\tfinal={r1['final_correct']}\t"
            f"rescue={r1['rescue']}\tregress={r1['regress']}\tacc={r1['accepted']}"
        )

        # V2 surface: delta only
        best_v2 = r1
        for d in deltas:
            r = apply_single_best(props, ship, d, None, None)
            fo.write(
                f"V2\t{d}\t\t{r['accepted']}\t{r['pos_fix']}\t{r['pos_break']}\t"
                f"{r['rescue']}\t{r['regress']}\t{r['net']}\t{r['final_correct']}\t"
                f"{r['rescue_a']}\t{r['rescue_b']}\t{r['regress_a']}\t{r['regress_b']}\n"
            )
            if r["net"] > best_v2["net"]:
                best_v2 = r
        log(f"V2_BEST\tnet={best_v2['net']}\tdelta={best_v2['delta_min']}\t{best_v2}")

        # V3 surface: delta x H
        best_v3 = r1
        surface = []
        for d in deltas:
            for h in hs:
                r = apply_single_best(props, ship, d, h, None)
                surface.append(r)
                fo.write(
                    f"V3\t{d}\t{h}\t{r['accepted']}\t{r['pos_fix']}\t{r['pos_break']}\t"
                    f"{r['rescue']}\t{r['regress']}\t{r['net']}\t{r['final_correct']}\t"
                    f"{r['rescue_a']}\t{r['rescue_b']}\t{r['regress_a']}\t{r['regress_b']}\n"
                )
                if r["net"] > best_v3["net"] or (
                    r["net"] == best_v3["net"] and r["accepted"] < best_v3.get("accepted", 10**9)
                ):
                    best_v3 = r
        log(f"V3_BEST\tnet={best_v3['net']}\tdelta={best_v3['delta_min']}\th={best_v3['h_min']}")

        # Plateau check for V3 best
        bd, bh = best_v3["delta_min"], best_v3["h_min"]
        neighbors = []
        for d in deltas:
            for h in hs:
                if abs(d - bd) < 1e-12 and abs((h or 0) - (bh or 0)) < 1e-12:
                    continue
                if abs(d - bd) <= 0.5 + 1e-9 or (
                    bh is not None and abs(h - bh) <= 0.5 + 1e-9
                ):
                    # immediate grid neighbors: adjacent indices
                    pass
        # proper neighbors: index ±1
        di = deltas.index(bd) if bd in deltas else 0
        hi = hs.index(bh) if bh in hs else 0
        for di2 in range(max(0, di - 1), min(len(deltas), di + 2)):
            for hi2 in range(max(0, hi - 1), min(len(hs), hi + 2)):
                if di2 == di and hi2 == hi:
                    continue
                r = apply_single_best(props, ship, deltas[di2], hs[hi2], None)
                neighbors.append((deltas[di2], hs[hi2], r["net"], r["accepted"]))
        log(f"V3_NEIGHBORS\t{neighbors}")
        plateau = sum(1 for _, _, n, _ in neighbors if n == best_v3["net"])
        near = sum(1 for _, _, n, _ in neighbors if n >= best_v3["net"] - 1)
        log(f"V3_PLATEAU\tsame_net_neighbors={plateau}\twithin1={near}\tn_neighbors={len(neighbors)}")

        # V4 surface
        best_v4 = apply_v4_nbest(nb_rows, ship, ent_by_sp, 0.0, 0.0, None)
        for d in deltas:
            for h in hs:
                r = apply_v4_nbest(nb_rows, ship, ent_by_sp, d, h, None)
                fo.write(
                    f"V4\t{d}\t{h}\t{r['accepted']}\t{r['pos_fix']}\t{r['pos_break']}\t"
                    f"{r['rescue']}\t{r['regress']}\t{r['net']}\t{r['final_correct']}\t"
                    f"{r['rescue_a']}\t{r['rescue_b']}\t{r['regress_a']}\t{r['regress_b']}\n"
                )
                if r["net"] > best_v4["net"]:
                    best_v4 = r
        log(f"V4_BEST\tnet={best_v4['net']}\tdelta={best_v4['delta_min']}\th={best_v4['h_min']}\t{best_v4}")

        # V5 surface
        best_v5 = apply_single_best(props, ship, 0.0, None, None, allow_v5)
        for d in deltas:
            for h in hs:
                r = apply_single_best(props, ship, d, h, None, allow_v5)
                fo.write(
                    f"V5\t{d}\t{h}\t{r['accepted']}\t{r['pos_fix']}\t{r['pos_break']}\t"
                    f"{r['rescue']}\t{r['regress']}\t{r['net']}\t{r['final_correct']}\t"
                    f"{r['rescue_a']}\t{r['rescue_b']}\t{r['regress_a']}\t{r['regress_b']}\n"
                )
                if r["net"] > best_v5["net"]:
                    best_v5 = r
        log(f"V5_BEST\tnet={best_v5['net']}\tdelta={best_v5['delta_min']}\th={best_v5['h_min']}\t{best_v5}")

    # split-half
    sh_results = {}
    for mode in ("v2c", "v2c_h", "v4", "v5"):
        allow = allow_v5 if mode == "v5" else None
        sh = split_half_validate(
            props,
            ship,
            nb_rows,
            ent_by_sp,
            mode,
            allow_pos=allow,
        )
        sh_results[mode] = sh
        log(
            f"SPLIT_HALF\t{mode}\twin_rate={sh['win_rate']:.2%}\t"
            f"mean_B_net={sh['mean_b_net']:.2f}\tmean_A_net={sh['mean_a_net']:.2f}\t"
            f"median_B_net={sh['median_b_net']:.2f}"
        )

    # --- Step 4 position-level rates ---
    total_chars = len(ent_rows)
    char_ok_ship = sum(1 for r in ent_rows if r["correct"] == "1")
    log(f"CHAR_OK_SHIP\t{char_ok_ship}/{total_chars}\t{100*char_ok_ship/total_chars:.4f}%")
    for name, res in [
        ("V1", r1),
        ("V2", best_v2),
        ("V3", best_v3),
        ("V4", best_v4),
        ("V5", best_v5),
    ]:
        # approximate new char ok = ship + pos_fix - pos_break
        new_ok = char_ok_ship + res["pos_fix"] - res["pos_break"]
        log(
            f"POS_LEVEL\t{name}\tfix={res['pos_fix']}\tbreak={res['pos_break']}\t"
            f"char_ok≈{new_ok}/{total_chars}\t{100*new_ok/total_chars:.4f}%"
        )

    # --- Step 5 quadrants ---
    Hs_all = [fnum(r["H_bits"]) for r in ent_rows]
    Hs_ok = [fnum(r["H_bits"]) for r in ent_rows if r["correct"] == "1"]
    Hs_bad = [fnum(r["H_bits"]) for r in ent_rows if r["correct"] == "0"]
    # fixed thresholds
    def quad(h_hi: float, h_lo: float):
        q = {"ok_low": 0, "ok_high": 0, "bad_low": 0, "bad_high": 0, "ok_mid": 0, "bad_mid": 0}
        for r in ent_rows:
            H = fnum(r["H_bits"])
            ok = r["correct"] == "1"
            if H >= h_hi:
                key = "ok_high" if ok else "bad_high"
            elif H < h_lo:
                key = "ok_low" if ok else "bad_low"
            else:
                key = "ok_mid" if ok else "bad_mid"
            q[key] += 1
        return q

    q_fixed = quad(1.0, 0.5)
    log(f"QUAD_FIXED\t{q_fixed}")
    # tertile on all H
    sorted_H = sorted(Hs_all)
    t1 = sorted_H[len(sorted_H) // 3]
    t2 = sorted_H[2 * len(sorted_H) // 3]
    log(f"TERTILES\tlow<{t1:.6f}\tmid\thigh>={t2:.6f}")
    q_ter = {"ok_low": 0, "ok_mid": 0, "ok_high": 0, "bad_low": 0, "bad_mid": 0, "bad_high": 0}
    for r in ent_rows:
        H = fnum(r["H_bits"])
        ok = r["correct"] == "1"
        if H >= t2:
            band = "high"
        elif H < t1:
            band = "low"
        else:
            band = "mid"
        q_ter[("ok_" if ok else "bad_") + band] += 1
    log(f"QUAD_TERTILE\t{q_ter}")

    # --- Fano ---
    mean_H_all = statistics.mean(Hs_all)
    mean_H_bad = statistics.mean(Hs_bad)
    mean_M = statistics.mean(inum(r["|C|"]) for r in ent_rows)
    pe_std, pe_weak = fano_bound(mean_H_all, mean_M)
    pe_std_bad, pe_weak_bad = fano_bound(mean_H_bad, mean_M)
    log(f"FANO_ALL\tH={mean_H_all:.4f}\tM={mean_M:.2f}\tPe_std>={pe_std:.4f}\tPe_weak>={pe_weak:.4f}")
    log(
        f"FANO_BAD\tH={mean_H_bad:.4f}\tM={mean_M:.2f}\tPe_std>={pe_std_bad:.4f}\t"
        f"Pe_weak>={pe_weak_bad:.4f}"
    )
    # sentence-level residual: if each position independent Pe, P(sent err) rough
    avg_len = total_chars / 537
    # lower bound on expected wrong positions
    min_wrong_pos = pe_std * total_chars
    log(f"FANO_MIN_WRONG_POS\t{min_wrong_pos:.1f}\tof\t{total_chars}")
    # theoretical max correct sentences if only min errors (optimistic packing)
    # cannot convert position Pe to sentence easily without independence; report position bound only
    max_char_acc = 1 - pe_std
    log(f"FANO_MAX_CHAR_ACC\t{max_char_acc:.4%}\t(shipping={char_ok_ship/total_chars:.4%})")

    # --- Step 7 position profile ---
    # load cases for sentence lengths
    cases_path = repo / "Source/Engine/eval/benchmarks/tw538-northstar.tsv"
    cases = []
    for line in cases_path.read_text(encoding="utf-8").splitlines():
        if not line or line[0] == "#":
            continue
        r, e = line.split("\t", 1)
        cases.append((r, e))

    err_rows = [r for r in ent_rows if r["correct"] == "0"]
    # single_char_swap: pred and gold same length, Hamming distance 1? Or wrong positions where only that char differs in a mostly-correct sent
    # Use: sentence has exactly 1 wrong position
    wrong_pos_per_sent = Counter(inum(r["sent_idx"]) for r in err_rows)
    single_err_sents = {s for s, c in wrong_pos_per_sent.items() if c == 1}
    scs = [r for r in err_rows if inum(r["sent_idx"]) in single_err_sents]

    def pos_profile(rows, label):
        rel = []
        right_rem = []
        left_ctx = []
        for r in rows:
            si = inum(r["sent_idx"])
            pos = inum(r["pos"])
            L = len(cases[si][1])
            rel.append(pos / max(L - 1, 1))
            right_rem.append(L - 1 - pos)
            left_ctx.append(pos)
        # 5 buckets
        buckets = [0] * 5
        for x in rel:
            b = min(4, int(x * 5))
            buckets[b] += 1
        log(
            f"POS_PROFILE\t{label}\tn={len(rows)}\t"
            f"rel_buckets={buckets}\t"
            f"right_mean={statistics.mean(right_rem) if right_rem else 0:.2f}\t"
            f"right_median={statistics.median(right_rem) if right_rem else 0:.1f}\t"
            f"left_mean={statistics.mean(left_ctx) if left_ctx else 0:.2f}\t"
            f"right0={sum(1 for x in right_rem if x==0)}\t"
            f"right_le1={sum(1 for x in right_rem if x<=1)}\t"
            f"right_ge3={sum(1 for x in right_rem if x>=3)}"
        )
        return right_rem, left_ctx, buckets

    rr_all, _, _ = pos_profile(err_rows, "all_err")
    rr_scs, _, _ = pos_profile(scs, "single_char_err_sent")

    # --- Step 8 sentence difficulty ---
    sent_stats = []
    by_s: dict[int, list[dict]] = defaultdict(list)
    for r in ent_rows:
        by_s[inum(r["sent_idx"])].append(r)
    for si in range(537):
        rows = by_s[si]
        Hs = [fnum(r["H_bits"]) for r in rows]
        ranks = [inum(r["gold_rank"]) for r in rows if r["gold_rank"] not in ("", "-1")]
        Ms = [inum(r["|C|"]) for r in rows]
        ship_ok = ship[si]["correct"] == "1"
        n_err = sum(1 for r in rows if r["correct"] == "0")
        maxH, meanH = max(Hs), statistics.mean(Hs)
        min_rank = min(ranks) if ranks else 99
        # labeling logic:
        # 过易: shipping correct AND maxH < 0.5 AND all gold_rank==1
        # 过难: shipping wrong AND (maxH>=1.5 or min_rank>=5 or n_err>=3)
        # 有鉴别度: else
        all_r1 = all(inum(r["gold_rank"]) == 1 for r in rows if r["gold_rank"] not in ("", "-1"))
        if ship_ok and maxH < 0.5 and all_r1:
            label = "过易"
        elif (not ship_ok) and (maxH >= 1.5 or min_rank >= 5 or n_err >= 3):
            label = "过难"
        else:
            label = "有鉴别度"
        sent_stats.append(
            {
                "sent_idx": si,
                "ship_ok": int(ship_ok),
                "n_err": n_err,
                "max_H": maxH,
                "mean_H": meanH,
                "min_gold_rank": min_rank,
                "mean_M": statistics.mean(Ms),
                "label": label,
            }
        )
    diff_path = analysis / "tw538-sentence-difficulty.tsv"
    with diff_path.open("w", encoding="utf-8") as fo:
        fo.write(
            "sent_idx\tship_ok\tn_err\tmax_H\tmean_H\tmin_gold_rank\tmean_M\tlabel\n"
        )
        for s in sent_stats:
            fo.write(
                f"{s['sent_idx']}\t{s['ship_ok']}\t{s['n_err']}\t{s['max_H']:.6f}\t"
                f"{s['mean_H']:.6f}\t{s['min_gold_rank']}\t{s['mean_M']:.2f}\t{s['label']}\n"
            )
    lab_c = Counter(s["label"] for s in sent_stats)
    log(f"DIFFICULTY_COUNTS\t{dict(lab_c)}")

    # --- Step 9 #155 ---
    r155, e155 = cases[155]
    log(f"CASE_155_READINGS\t{r155}")
    log(f"CASE_155_GOLD\t{e155}")
    log(f"CASE_155_NSYL\t{len(r155.split('-'))}")
    log(f"CASE_155_NCHAR\t{len(e155)}")
    log("CASE_155_NOTE\t满分实质 536/537；交接档「100%对齐」与事实不符")

    # Write reports
    write_reports(
        analysis,
        r1,
        best_v2,
        best_v3,
        best_v4,
        best_v5,
        sh_results,
        neighbors,
        q_fixed,
        q_ter,
        t1,
        t2,
        mean_H_all,
        mean_M,
        pe_std,
        pe_weak,
        char_ok_ship,
        total_chars,
        rr_all,
        rr_scs,
        lab_c,
        cases,
        err_rows,
        scs,
    )

    out_log.write_text("\n".join(log_lines) + "\n", encoding="utf-8")
    log(f"WROTE_LOG\t{out_log}\tsha={sha256(out_log)}")
    log(f"SWEEP_SHA\t{sha256(sweep_path)}")
    return 0


def write_reports(
    analysis: Path,
    r1,
    best_v2,
    best_v3,
    best_v4,
    best_v5,
    sh_results,
    neighbors,
    q_fixed,
    q_ter,
    t1,
    t2,
    mean_H_all,
    mean_M,
    pe_std,
    pe_weak,
    char_ok_ship,
    total_chars,
    rr_all,
    rr_scs,
    lab_c,
    cases,
    err_rows,
    scs,
):
    # gate report
    def fmt_r(name, r, sh_key):
        sh = sh_results.get(sh_key, {})
        return (
            f"| {name} | {r['net']:+d} | {r['final_correct']}/537 | "
            f"{r['rescue']}/{r['regress']} | {r['pos_fix']}/{r['pos_break']} | "
            f"δ≥{r['delta_min']}"
            + (f", H≥{r['h_min']}" if r.get("h_min") is not None else "")
            + f" | {sh.get('win_rate', float('nan')):.0%} | {sh.get('mean_b_net', float('nan')):+.1f} |"
        )

    # decision from held-out
    best_heldout = max(
        (
            ("V2", sh_results["v2c"]["mean_b_net"], sh_results["v2c"]["win_rate"]),
            ("V3", sh_results["v2c_h"]["mean_b_net"], sh_results["v2c_h"]["win_rate"]),
            ("V4", sh_results["v4"]["mean_b_net"], sh_results["v4"]["win_rate"]),
            ("V5", sh_results["v5"]["mean_b_net"], sh_results["v5"]["win_rate"]),
        ),
        key=lambda x: x[1],
    )
    # GO only if win_rate>=50% AND mean_b_net meets thresholds
    decision = "NO-GO"
    if best_heldout[2] >= 0.5:
        if best_heldout[1] >= 30:
            decision = "GO"
        elif best_heldout[1] >= 15:
            decision = "边际"
        else:
            decision = "NO-GO"
    else:
        decision = "NO-GO（split-half 过拟合/不稳）"

    gate_md = f"""# tw538 单点翻字闸门扫描报告（棒 A-2）

**日期**：2026-07-28  
**性质**：纯分析；未改 app／引擎／出货配置。  
**起点**：棒 A 无闸门净 −45（NO-GO）。

## 步骤 1 主表栏位

`tw538-residual-entropy.tsv` 栏位：

`sent_idx, pos, reading, gold, pred, correct, H_bits, gold_rank, gold_prob, |C|`

**熵前缀：gold teacher-forcing**（`homophone_measure.cpp` 中 `prefix = gold[0..i)`），**不是** walk 输出前缀。

| 需求栏位 | 状态 |
|---------|------|
| 目前输出字 pred | 有 |
| gold | 有 |
| gold rank / prob | 有 |
| 候选数 M | 有（`|C|`） |
| 句级对错 | 由 shipping_preds 另表 |
| error_class A/B | **无**；由 `gold_in_pool` 派生 |
| top1 字 / top1 概率 / margin | **无**；补齐需重跑约 30min 熵前向 → **本棒跳过重跑** |

前 3 列见分析 stdout。

## 方法

- 自 shipping 输出做**所有**单字同音翻提案（`flip_proposal_dump`），`Δscore = v2c(S')−v2c(S)`。
- 每句最多接受 **1** 个通过闸门且 `Δ` 最大的提案（round-1 风格；不跑第 2 轮，以免与闸门搜索耦合爆炸）。
- **闸门**：`Δscore ≥ δ_min` 且（可选）`H ≥ h_min`（H 为该位置 gold 前缀残馀熵）。
- 格点：`δ ∈ {{0, 0.05, 0.1, 0.2, 0.5, 1, 1.5, 2, 3}}`；`H_min ∈ {{0, 0.1, 0.25, 0.5, 0.75, 1, 1.5, 2}}`。
- **V4**：在 n-best 路径集合上用 `walkScore + 0.75·v2c` 选路；H 门控用**所有改动位置的 max H**。
- **V5**：仅允许棒 A 所述「gold_rank==1 且位置答错」的 85 类位置（本表实际计数见 stdout `V5_POS_N`）。

## 五变体对照（全量调参半）

| 变体 | 净增益 | 终句正确 | RESCUE/REGRESS | 位 fix/break | 最佳闸门 | split-half 胜率 | held-out 平均净增益 |
|------|--------|----------|----------------|--------------|----------|-----------------|---------------------|
{fmt_r("V1 无闸门", r1, "v2c")}
{fmt_r("V2 Δ only", best_v2, "v2c")}
{fmt_r("V3 Δ+H", best_v3, "v2c_h")}
{fmt_r("V4 walk+ v2c", best_v4, "v4")}
{fmt_r("V5 rank1-only", best_v5, "v5")}

完整曲面：`tw538-flip-gate-sweep.tsv`。

### 高原 vs 尖峰（V3 最佳点）

最佳 V3：δ={best_v3['delta_min']}, H≥{best_v3['h_min']}, net={best_v3['net']:+d}  
邻格：{neighbors}

### split-half（20 次；A 半选闸门，B 半评估）

| 模式 | 胜出率 (B净>0) | B 平均净增益 | A 平均净增益 |
|------|----------------|--------------|--------------|
| V2 | {sh_results['v2c']['win_rate']:.0%} | {sh_results['v2c']['mean_b_net']:+.2f} | {sh_results['v2c']['mean_a_net']:+.2f} |
| V3 | {sh_results['v2c_h']['win_rate']:.0%} | {sh_results['v2c_h']['mean_b_net']:+.2f} | {sh_results['v2c_h']['mean_a_net']:+.2f} |
| V4 | {sh_results['v4']['win_rate']:.0%} | {sh_results['v4']['mean_b_net']:+.2f} | {sh_results['v4']['mean_a_net']:+.2f} |
| V5 | {sh_results['v5']['win_rate']:.0%} | {sh_results['v5']['mean_b_net']:+.2f} | {sh_results['v5']['mean_a_net']:+.2f} |

**判定用 held-out（B 半）**：最佳为 **{best_heldout[0]}**，B 平均净增益 **{best_heldout[1]:+.2f}**，胜出率 **{best_heldout[2]:.0%}**。

### 最终判定（held-out）：**{decision}**

（门限：≥+30 GO ／ +15~+29 边际 ／ <+15 NO-GO；胜出率 <50% 一律不采信调参峰值。）

## V4 与 REGRESS

V4 最佳：RESCUE={best_v4['rescue']}（A={best_v4['rescue_a']}/B={best_v4['rescue_b']}），REGRESS={best_v4['regress']}（A={best_v4['regress_a']}/B={best_v4['regress_b']}）。  
相对 V1 无闸门 REGRESS {r1['regress']} → V4 {best_v4['regress']}。

## 负结果声明

若全部 held-out 净增益 ≤0 或胜出率 <50%，单点翻字路线（含闸门与 walk 融合）应正式关闭，不进入训练棒 C。
"""
    (analysis / "tw538-flip-gate-report.md").write_text(gate_md, encoding="utf-8")

    # quadrants + fano
    quad_md = f"""# tw538 残馀熵四格 + Fano 下界（棒 A-2）

## 熵前缀

**gold teacher-forcing**（非 walk 前缀）。

## 固定门限四格（H≥1.0 高，H<0.5 低）

|  | 位置答对 | 位置答错 |
|--|----------|----------|
| **低熵** | ① {q_fixed['ok_low']} | ② {q_fixed['bad_low']}（学错了） |
| **中熵** | {q_fixed['ok_mid']} | {q_fixed['bad_mid']} |
| **高熵** | ③ {q_fixed['ok_high']}（**矇对**） | ④ {q_fixed['bad_high']}（真不会） |

**③ 矇对**：{q_fixed['ok_high']} / {char_ok_ship} 答对位置 = **{100*q_fixed['ok_high']/max(char_ok_ship,1):.2f}%** 的答对来自高熵。  
占全体位置 {100*q_fixed['ok_high']/total_chars:.2f}%；相对 387 句没有直接一一映射，但显示「分数里有一批低把握猜对」。

## 分位门限（全体 H 三分位）

- 低：H < {t1:.6f}
- 中：{t1:.6f} ≤ H < {t2:.6f}
- 高：H ≥ {t2:.6f}

|  | 答对 | 答错 |
|--|------|------|
| 低熵 | {q_ter['ok_low']} | {q_ter['bad_low']} |
| 中熵 | {q_ter['ok_mid']} | {q_ter['bad_mid']} |
| 高熵 | {q_ter['ok_high']} | {q_ter['bad_high']} |

结论是否翻转：固定门限下「低熵答错=学错」{q_fixed['bad_low']} 笔；三分位因整体 H 中位数仅 ~0.085，**高熵桶定义更严/更松会变**，但「答错集中在相对更高熵」方向一致。

## Fano 下界

形式：

```
H(X|Y) ≤ h(P_e) + P_e · log₂(|X|−1)
```

假设：把每位同音选择近似为 |X|=M 的分类，H 取残馀熵（限制在 C_i 后）。

数值（全体位置）：H̄={mean_H_all:.4f} bits，M̄={mean_M:.2f}

| 形式 | P_e 下界 |
|------|----------|
| 标准 Fano（数值反解） | **{pe_std:.4f}** |
| 弱化式 (H−1)/log₂(M) | {pe_weak:.4f} |

→ 字级正确率上界 ≤ **{100*(1-pe_std):.2f}%**（出货 96.50%）。  
**用途**：只能证明「做不到任意低错误」，**不能**保证「还能再救多少句」。刹车不是油门。

字级错误下界约 {pe_std*total_chars:.0f} 字 / {total_chars}；无法在不引入独立性假设下严格换成「还可救几句」。
"""
    (analysis / "tw538-entropy-quadrants.md").write_text(quad_md, encoding="utf-8")

    # position profile
    def hist5(vals):
        # for right remaining, not rel
        return vals

    prof_md = f"""# tw538 错字位置剖面（棒 A-2）

## 假设

「单字同音错最需要右侧上下文」。若错字多在句尾，右侧無料，双方向判別器价值下降。

## 全部错误位置（n={len(err_rows)}）

- 右侧剩余字数：mean={statistics.mean(rr_all):.2f}，median={statistics.median(rr_all):.1f}
- 右侧=0（句末字）：{sum(1 for x in rr_all if x==0)}（{100*sum(1 for x in rr_all if x==0)/max(len(rr_all),1):.1f}%）
- 右侧≤1：{sum(1 for x in rr_all if x<=1)}
- 右侧≥3：{sum(1 for x in rr_all if x>=3)}

## single_char 错句子集（句内恰 1 个错位，n={len(scs)}）

- 右侧剩余：mean={statistics.mean(rr_scs) if rr_scs else 0:.2f}，median={statistics.median(rr_scs) if rr_scs else 0:.1f}
- 右侧=0：{sum(1 for x in rr_scs if x==0) if rr_scs else 0}
- 右侧≥3：{sum(1 for x in rr_scs if x>=3) if rr_scs else 0}

## 一句话结论

**这批错误平均右侧仍剩约 {statistics.mean(rr_all):.1f} 个字**（single_char 子集约 {statistics.mean(rr_scs) if rr_scs else 0:.1f} 个）；
{"右侧上下文整体有料，双向/右文模型仍有发挥空间" if statistics.mean(rr_all) >= 2 else "右侧偏短，句末错占比不低，右文价值有限"}。
"""
    (analysis / "tw538-error-position-profile.md").write_text(prof_md, encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
