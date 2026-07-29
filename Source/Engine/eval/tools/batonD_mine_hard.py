#!/usr/bin/env python3
"""Baton D: confusion-pair table + hard-sample mining from real spoken corpus.

Does NOT synthesize sentences. Mines:
  2-1 confusion-pair guided lines
  2-2 model-error guided lines (shipping v2c next-char top-1 ≠ gold)

Outputs under ~/laowang-data/batonD-final/traindata/
"""
from __future__ import annotations

import hashlib
import json
import random
import struct
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import torch
import torch.nn as nn

ROOT = Path.home() / "iBopomofo"
DATA = Path.home() / "laowang-data"
OUT = DATA / "batonD-final"
TD = OUT / "traindata"
CORPUS = DATA / "ptt_spoken_train_v2.txt"
V2C_BIN = ROOT / "Source/Engine/eval/models/path-char-lstm-spoken-v2c.bin"
TW538 = ROOT / "Source/Engine/eval/benchmarks/tw538-northstar.tsv"
ERR_MAP = ROOT / "Source/Engine/eval/analysis/tw538-error-map.tsv"
RES_ENT = ROOT / "Source/Engine/eval/analysis/tw538-residual-entropy.tsv"
SHIP = DATA / "batonA2-gate-dump/shipping_preds.tsv"
CONF_TSV = ROOT / "Source/Engine/eval/analysis/confusion-pair-frequency.tsv"

sys.path.insert(0, str(ROOT / "Source/Engine/eval/analysis"))
from classify_tw538_errors import classify_a  # noqa: E402

HAN = set(chr(c) for c in range(0x4E00, 0x9FFF + 1))
PUNCT = set("，。！？、；：,.!?;:「」『』（）()…—-")


class CharLSTM(nn.Module):
    def __init__(self, vocab, emb, hidden, layers):
        super().__init__()
        self.emb = nn.Embedding(vocab, emb, padding_idx=0)
        self.lstm = nn.LSTM(emb, hidden, num_layers=layers, batch_first=True)
        self.fc = nn.Linear(hidden, vocab)

    def forward(self, x):
        return self.fc(self.lstm(self.emb(x))[0])


def load_lwlstm1(path: Path, device: torch.device):
    raw = path.read_bytes()
    assert raw[:8] == b"LWLSTM1\0", raw[:8]
    emb, hid, layers, vocab = struct.unpack_from("<iiii", raw, 8)
    off = 8 + 16
    itos = []
    for _ in range(vocab):
        (n,) = struct.unpack_from("<h", raw, off)
        off += 2
        itos.append(raw[off : off + n].decode("utf-8"))
        off += n
    stoi = {c: i for i, c in enumerate(itos)}

    def take(shape):
        nonlocal off
        n = 1
        for d in shape:
            n *= d
        nbytes = n * 4
        t = torch.frombuffer(bytearray(raw[off : off + nbytes]), dtype=torch.float32).clone()
        off += nbytes
        return t.view(*shape)

    model = CharLSTM(vocab, emb, hid, layers)
    sd = {
        "emb.weight": take((vocab, emb)),
        **{
            k: take(s)
            for li in range(layers)
            for k, s in [
                (f"lstm.weight_ih_l{li}", (4 * hid, emb if li == 0 else hid)),
                (f"lstm.weight_hh_l{li}", (4 * hid, hid)),
                (f"lstm.bias_ih_l{li}", (4 * hid,)),
                (f"lstm.bias_hh_l{li}", (4 * hid,)),
            ]
        },
        "fc.weight": take((vocab, hid)),
        "fc.bias": take((vocab,)),
    }
    model.load_state_dict(sd)
    model.to(device).eval()
    return model, itos, stoi, {"emb": emb, "hid": hid, "layers": layers, "vocab": vocab}


def conf_super(lab: str) -> str:
    if lab.startswith("single_char_swap"):
        return "single_char_swap"
    if lab.startswith("multi_char_swap"):
        return "multi_char_swap"
    if lab.startswith(("homophone_", "particle_", "pronoun_", "measure_")):
        return "homophone_family"
    return lab.split("(")[0]


def step1_confusion_table(corpus_lines: list[str]) -> list[dict]:
    """Build wrong→gold pair ranking + corpus frequencies."""
    rows = []
    # From residual entropy: positions where pred!=gold
    el = RES_ENT.read_text(encoding="utf-8").splitlines()
    eh = el[0].split("\t")
    pair_err = Counter()
    pair_single = Counter()
    for L in el[1:]:
        d = dict(zip(eh, L.split("\t")))
        if d.get("correct") == "1":
            continue
        g, p = d.get("gold", ""), d.get("pred", "")
        if g and p and g != p and len(g) == 1 and len(p) == 1:
            pair_err[(p, g)] += 1
            # mark single-char style
            pair_single[(p, g)] += 1

    # Also sentence-level A-class from error map / shipping for patterns
    ships = {}
    if SHIP.exists():
        sl = SHIP.read_text(encoding="utf-8").splitlines()
        sh = sl[0].split("\t")
        for L in sl[1:]:
            d = dict(zip(sh, L.split("\t")))
            ships[int(d["sent_idx"])] = d

    cases = []
    for L in TW538.read_text(encoding="utf-8").splitlines():
        if not L or L[0] == "#":
            continue
        a, b = L.split("\t", 1)
        cases.append((a, b))

    sent_patterns = Counter()
    for i, (_, gold) in enumerate(cases):
        if i not in ships or ships[i].get("correct") == "1":
            continue
        pred = ships[i]["pred"]
        lab = conf_super(classify_a(gold, pred))
        sent_patterns[lab] += 1
        if lab == "single_char_swap" and len(gold) == len(pred):
            for gc, pc in zip(gold, pred):
                if gc != pc:
                    pair_err[(pc, gc)] += 0  # already counted from residual
                    pair_single[(pc, gc)] += 0

    # corpus unigram counts for involved chars
    need_chars = set()
    for p, g in pair_err:
        need_chars.add(p)
        need_chars.add(g)
    char_freq = Counter()
    for line in corpus_lines:
        for ch in line:
            if ch in need_chars:
                char_freq[ch] += 1

    ranked = pair_err.most_common()
    out_rows = []
    lines = [
        "rank\twrong\tgold\terr_count\tgold_freq\twrong_freq\tfreq_ratio_gold_over_wrong\tsingle_char_flag\n"
    ]
    for rank, ((wrong, gold), nerr) in enumerate(ranked, 1):
        gf = char_freq.get(gold, 0)
        wf = char_freq.get(wrong, 0)
        ratio = (gf / wf) if wf > 0 else float("inf")
        sc = 1 if (wrong, gold) in pair_single else 0
        lines.append(
            f"{rank}\t{wrong}\t{gold}\t{nerr}\t{gf}\t{wf}\t{ratio:.4f}\t{sc}\n"
        )
        out_rows.append(
            {
                "rank": rank,
                "wrong": wrong,
                "gold": gold,
                "err": nerr,
                "gold_freq": gf,
                "wrong_freq": wf,
                "ratio": ratio,
            }
        )
    CONF_TSV.write_text("".join(lines), encoding="utf-8")
    (TD / "confusion_meta.json").write_text(
        json.dumps(
            {
                "n_pairs": len(out_rows),
                "sent_patterns": dict(sent_patterns),
                "top10": out_rows[:10],
                "high_freq_err": sum(1 for r in out_rows if r["gold_freq"] >= 100_000),
                "low_freq_err": sum(1 for r in out_rows if r["gold_freq"] < 10_000),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return out_rows


def mine_pair_lines(
    corpus_lines: list[str], pairs: list[dict], top_n: int, max_lines: int, rng: random.Random
) -> tuple[list[str], dict]:
    keys = set()
    for r in pairs[:top_n]:
        keys.add(r["wrong"])
        keys.add(r["gold"])
    hits = []
    for line in corpus_lines:
        if any(c in line for c in keys):
            # prefer lines that contain at least one gold or wrong from top pairs
            hits.append(line)
    rng.shuffle(hits)
    selected = hits[:max_lines]
    return selected, {
        "top_n_pairs": top_n,
        "cand_lines": len(hits),
        "selected": len(selected),
        "positions_est": sum(sum(1 for c in L if c in keys) for L in selected),
    }


@torch.no_grad()
def mine_model_errors(
    corpus_lines: list[str],
    model,
    stoi: dict,
    device: torch.device,
    max_lines_scan: int,
    max_hard_lines: int,
    max_hours: float,
    rng: random.Random,
) -> tuple[list[str], dict]:
    t0 = time.time()
    idxs = list(range(len(corpus_lines)))
    rng.shuffle(idxs)
    # Keep (err_count, err_rate, line); later take highest-density errors.
    scored: list[tuple[int, float, str]] = []
    n_pos = n_err = scanned = 0
    unk = stoi.get("<unk>", 1)
    bos = stoi["<s>"]
    eos = stoi["</s>"]
    for ii in idxs:
        if scanned >= max_lines_scan:
            break
        if time.time() - t0 > max_hours * 3600:
            break
        line = corpus_lines[ii]
        chars = [c for c in line if c in HAN or c in PUNCT]
        if len(chars) < 4 or len(chars) > 80:
            continue
        scanned += 1
        ids = [bos] + [stoi.get(c, unk) for c in chars] + [eos]
        x = torch.tensor([ids[:-1]], device=device)
        logits = model(x)[0]  # T, V
        pred = logits.argmax(-1).tolist()
        gold = ids[1:]
        e = 0
        t = 0
        for p, g in zip(pred, gold):
            if g in (0, bos, eos):
                continue
            t += 1
            n_pos += 1
            if p != g:
                e += 1
                n_err += 1
        if e >= 2 and t > 0:  # at least 2 mistakes — true hard, not random noise
            scored.append((e, e / t, line))
        if scanned % 2000 == 0:
            print(
                f"  model-mine scanned={scanned} hard_cand={len(scored)} "
                f"err_rate={n_err/max(1,n_pos):.3f} h={(time.time()-t0)/3600:.2f}",
                flush=True,
            )
    # densest errors first
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    hard = [L for _, _, L in scored[:max_hard_lines]]
    return hard, {
        "scanned_lines": scanned,
        "hard_lines": len(hard),
        "hard_candidates": len(scored),
        "positions": n_pos,
        "err_positions": n_err,
        "err_rate": n_err / max(1, n_pos),
        "min_err_count_kept": scored[max_hard_lines - 1][0] if len(scored) >= max_hard_lines else (
            scored[-1][0] if scored else 0
        ),
        "elapsed_h": (time.time() - t0) / 3600,
    }


def min_diff_pairs(lines: list[str], max_check: int = 200_000) -> list[tuple[str, str]]:
    """Find real line pairs that differ by a single Han char (same length)."""
    by_len = defaultdict(list)
    for L in lines[:max_check]:
        h = "".join(c for c in L if c in HAN)
        if 6 <= len(h) <= 40:
            by_len[len(h)].append(h)
    found = []
    for n, group in by_len.items():
        if len(group) < 2 or len(group) > 50_000:
            # cap per length
            group = group[:20_000]
        # bucket by hash of all-but-one positions is expensive; sample
        buckets = defaultdict(list)
        for s in group:
            # key: all chars with middle masked styles - use prefix+suffix
            buckets[s[: n // 2] + s[n // 2 + 1 :]].append(s)
        for b in buckets.values():
            if len(b) < 2:
                continue
            for i in range(len(b)):
                for j in range(i + 1, min(i + 5, len(b))):
                    a, c = b[i], b[j]
                    diffs = [k for k in range(n) if a[k] != c[k]]
                    if len(diffs) == 1:
                        found.append((a, c))
                        if len(found) >= 5000:
                            return found
    return found


def pollution_check(lines: list[str]) -> int:
    golds = set()
    for L in TW538.read_text(encoding="utf-8").splitlines():
        if not L or L[0] == "#":
            continue
        golds.add(L.split("\t", 1)[1].strip())
    hits = 0
    gset = golds
    for line in lines:
        s = "".join(c for c in line if c in HAN)
        if s in gset:
            hits += 1
    return hits


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    TD.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    print("loading corpus...", flush=True)
    corpus_lines = [
        L.strip()
        for L in CORPUS.read_text(encoding="utf-8", errors="ignore").splitlines()
        if L.strip()
    ]
    print(f"corpus_lines={len(corpus_lines)}", flush=True)

    print("step1 confusion table...", flush=True)
    pairs = step1_confusion_table(corpus_lines)
    print(f"pairs={len(pairs)} top5={pairs[:5]}", flush=True)

    # rarity judgment
    top = pairs[:50]
    rare = sum(1 for r in top if r["gold_freq"] < 10_000)
    common = sum(1 for r in top if r["gold_freq"] >= 100_000)
    print(f"top50 rare(<10k)={rare} common(>=100k)={common}", flush=True)

    rng = random.Random(42)
    print("step2-1 pair mining...", flush=True)
    pair_lines, pair_stats = mine_pair_lines(corpus_lines, pairs, top_n=80, max_lines=400_000, rng=rng)
    print(pair_stats, flush=True)

    device = torch.device("mps" if torch.backends.mps.is_available() else "cpu")
    print(f"loading v2c on {device}...", flush=True)
    model, itos, stoi, arch = load_lwlstm1(V2C_BIN, device)
    print(f"v2c arch={arch}", flush=True)

    # budget: remaining of 2h mining hard cap for model path
    remain_h = max(0.1, 1.8 - (time.time() - t0) / 3600)
    print(f"step2-2 model-error mining max_h={remain_h:.2f}...", flush=True)
    hard_lines, hard_stats = mine_model_errors(
        corpus_lines,
        model,
        stoi,
        device,
        max_lines_scan=800_000,
        max_hard_lines=500_000,
        max_hours=remain_h,
        rng=rng,
    )
    print(hard_stats, flush=True)

    # min-diff bonus
    print("min-diff pairs...", flush=True)
    md = min_diff_pairs(corpus_lines, max_check=300_000)
    print(f"min_diff_pairs={len(md)}", flush=True)
    md_lines = []
    for a, b in md[:2000]:
        md_lines.append(a)
        md_lines.append(b)

    # merge unique hard set (preserve order-ish)
    seen = set()
    merged = []
    for src, bucket in (("model", hard_lines), ("pair", pair_lines), ("mindiff", md_lines)):
        for L in bucket:
            if L not in seen:
                seen.add(L)
                merged.append(L)

    # position count estimate
    pos_est = sum(len([c for c in L if c in HAN]) for L in merged)

    # punct retention
    with_punct = sum(1 for L in merged if any(c in PUNCT for c in L))

    # pollution
    pol = pollution_check(merged)
    print(f"pollution_hits={pol}", flush=True)
    if pol > 0:
        print("POLLUTION > 0 — STOP", flush=True)
        (TD / "POLLUTION_STOP.json").write_text(
            json.dumps({"hits": pol}, indent=2), encoding="utf-8"
        )
        return 2

    hard_path = TD / "hard_mined_real.txt"
    hard_path.write_text("\n".join(merged) + "\n", encoding="utf-8")

    # skip synth if no scarce high-error pairs in top ranks
    scarce = [r for r in pairs[:30] if r["gold_freq"] < 10_000 and r["err"] >= 2]
    synth_note = {
        "skipped": True,
        "reason": "no clearly scarce high-error pairs in top ranks requiring LLM fill"
        if not scarce
        else "scarce pairs exist but baton allows optional synth; skipping to keep isolation simple unless needed",
        "scarce_top30": scarce[:10],
    }
    # baton: if scarce, allow synth. We skip unless critical scarcity dominates.
    if scarce and sum(r["err"] for r in scarce) >= 20:
        synth_note["skipped"] = True
        synth_note["reason"] = (
            "scarce pairs present but total err mass low; skip synth to avoid "
            "confounding D1 vs D2 (will set D2=D1 and document)"
        )

    meta = {
        "corpus": str(CORPUS),
        "n_corpus_lines": len(corpus_lines),
        "pair_stats": pair_stats,
        "hard_stats": hard_stats,
        "min_diff_n": len(md),
        "merged_lines": len(merged),
        "positions_est": pos_est,
        "pair_only_lines": len(pair_lines),
        "model_only_lines": len(hard_lines),
        "model_vs_pair_extra": max(0, len(hard_lines) - len(set(hard_lines) & set(pair_lines))),
        "punct_lines": with_punct,
        "punct_ratio": with_punct / max(1, len(merged)),
        "pollution_hits": pol,
        "synth": synth_note,
        "hard_sha": sha256(hard_path),
        "elapsed_h": (time.time() - t0) / 3600,
        "target_positions": 5_000_000,
        "hit_target": pos_est >= 5_000_000,
    }
    (TD / "mine_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(meta, ensure_ascii=False, indent=2), flush=True)
    print("MINE_DONE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
