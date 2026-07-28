#!/usr/bin/env python3
"""Fast full evaluation for baton C final models."""
from __future__ import annotations

import json
import random
import time
from collections import defaultdict
from pathlib import Path

import torch
import torch.nn as nn

ROOT = Path.home() / "iBopomofo"
DATA = Path.home() / "laowang-data"
OUT = DATA / "batonC-final"
EXCL = {(155, p) for p in range(11, 16)}
BASE_A = 5947 / 6795
BASE_B = 367 / 537


class PosJudge(nn.Module):
    def __init__(self, n_char, n_rd, emb=256, hid=384, layers=2, rd_emb=64, drop=0.1):
        super().__init__()
        self.emb = nn.Embedding(n_char, emb, padding_idx=0)
        self.rd_emb = nn.Embedding(n_rd, rd_emb, padding_idx=0)
        self.lstm = nn.LSTM(
            emb,
            hid,
            num_layers=layers,
            batch_first=True,
            bidirectional=True,
            dropout=drop if layers > 1 else 0.0,
        )
        self.drop = nn.Dropout(drop)
        self.fc = nn.Linear(hid * 2 + rd_emb, n_char)

    def forward(self, ids, lengths, pos, rd):
        x = self.emb(ids)
        packed = nn.utils.rnn.pack_padded_sequence(
            x, lengths.cpu(), batch_first=True, enforce_sorted=False
        )
        out, _ = self.lstm(packed)
        out, _ = nn.utils.rnn.pad_packed_sequence(out, batch_first=True)
        B = ids.size(0)
        idx = pos.view(B, 1, 1).expand(B, 1, out.size(-1))
        h = out.gather(1, idx).squeeze(1)
        return self.fc(self.drop(torch.cat([h, self.rd_emb(rd)], -1)))


def load_r2c():
    r2c = {}
    for L in (DATA / "reading2chars.tsv").read_text(encoding="utf-8").splitlines():
        if not L or L[0] == "#":
            continue
        r, b = L.split("\t", 1)
        r2c[r] = [p.rsplit(":", 1)[0] for p in b.split(",") if ":" in p]
    return r2c


def load_cases():
    cases = []
    for L in (
        ROOT / "Source/Engine/eval/benchmarks/tw538-northstar.tsv"
    ).read_text(encoding="utf-8").splitlines():
        if not L or L[0] == "#":
            continue
        a, b = L.split("\t", 1)
        cases.append((a, b))
    return cases


def load_ships():
    Ls = (DATA / "batonA2-gate-dump/shipping_preds.tsv").read_text(
        encoding="utf-8"
    ).splitlines()
    h = Ls[0].split("\t")
    rows = []
    for L in Ls[1:]:
        p = L.split("\t")
        rows.append({h[i]: p[i] if i < len(p) else "" for i in range(len(h))})
    return rows


def load_nbest():
    nl = (DATA / "batonA2-gate-dump/nbest_paths.tsv").read_text(
        encoding="utf-8"
    ).splitlines()
    nh = nl[0].split("\t")
    by = defaultdict(list)
    for L in nl[1:]:
        d = dict(zip(nh, L.split("\t")))
        by[int(d["sent_idx"])].append(d)
    return by


def load_ent():
    el = (
        ROOT / "Source/Engine/eval/analysis/tw538-residual-entropy.tsv"
    ).read_text(encoding="utf-8").splitlines()
    eh = el[0].split("\t")
    ent = {}
    for L in el[1:]:
        d = dict(zip(eh, L.split("\t")))
        ent[(int(d["sent_idx"]), int(d["pos"]))] = d
    return ent


@torch.no_grad()
def eval_ckpt(ckpt_path: Path, tag: str):
    device = torch.device("mps" if torch.backends.mps.is_available() else "cpu")
    ckpt = torch.load(ckpt_path, map_location=device, weights_only=False)
    char2id, rd2id = ckpt["char2id"], ckpt["rd2id"]
    id2char = {i: c for c, i in char2id.items()}
    model = PosJudge(len(char2id), len(rd2id)).to(device)
    model.load_state_dict(ckpt["model"])
    model.eval()

    r2c = load_r2c()
    cases = load_cases()
    ships = load_ships()
    nbest = load_nbest()
    ent = load_ent()

    def forward_logits(chars, pos, rd):
        ids = [char2id.get(c, char2id["<unk>"]) for c in chars]
        ids[pos] = char2id["<mask>"]
        t = torch.tensor([ids], device=device)
        lengths = torch.tensor([len(ids)])
        pos_t = torch.tensor([pos], device=device)
        rd_t = torch.tensor([rd2id.get(rd, 0)], device=device)
        return model(t, lengths, pos_t, rd_t)[0]

    def argmax_cand(logits, cands):
        cids = [char2id.get(c, char2id["<unk>"]) for c in cands]
        idx = torch.tensor(cids, device=device)
        return id2char.get(
            int(idx[int(logits.index_select(0, idx).argmax())]), cands[0]
        )

    g1_ok = g1_n = g2_ok = g2_n = 0
    free_n = free_ok = frag_n = frag_ok = 0
    rows = []
    t0 = time.time()

    for si, (readings, gold) in enumerate(cases):
        syls = [s for s in readings.split("-") if s]
        gchars = list(gold)
        schars = list(ships[si]["pred"])
        n = min(len(syls), len(gchars), len(schars))
        for i in range(n):
            if (si, i) in EXCL:
                continue
            rd = syls[i]
            cands = r2c.get(rd, [])
            if gchars[i] not in cands:
                cands = list(cands) + [gchars[i]]
            if not cands:
                continue
            lg = forward_logits(gchars[:n], i, rd)
            ls = forward_logits(schars[:n], i, rd)
            pg = argmax_cand(lg, cands)
            ps = argmax_cand(ls, cands)
            ok1 = pg == gchars[i]
            ok2 = ps == gchars[i]
            g1_n += 1
            g2_n += 1
            if ok1:
                g1_ok += 1
            if ok2:
                g2_ok += 1
            er = ent.get((si, i), {})
            try:
                H = float(er.get("H_bits", "nan"))
            except ValueError:
                H = float("nan")
            gr = er.get("gold_rank", "")
            ship_ok = schars[i] == gchars[i]
            if ship_ok and H == H and H >= 1.0:
                frag_n += 1
                if ok2:
                    frag_ok += 1
            if gr == "1" and not ship_ok:
                free_n += 1
                if ok2:
                    free_ok += 1
            rows.append(
                (
                    si,
                    i,
                    rd,
                    gchars[i],
                    schars[i],
                    pg,
                    int(ok1),
                    ps,
                    int(ok2),
                    H,
                    gr,
                    ships[si].get("gold_in_pool", ""),
                )
            )
        if (si + 1) % 100 == 0:
            print(f"{tag} positions {si+1}/537", flush=True)

    print(f"{tag} path scoring...", flush=True)
    t1 = time.time()
    path_new = {}
    gold_first = 0
    inpool = 0
    gold_first_in = 0

    def score_path(text, syls):
        chars = list(text)
        n = min(len(chars), len(syls))
        s = 0.0
        for i in range(n):
            logits = forward_logits(chars[:n], i, syls[i])
            cid = char2id.get(chars[i], char2id["<unk>"])
            row = logits - logits.max()
            logp = row - torch.log(torch.exp(row).sum())
            s += float(logp[cid])
        return s

    for si, (readings, gold) in enumerate(cases):
        syls = [s for s in readings.split("-") if s]
        paths = nbest.get(si, [])
        has_gold = any(p["is_gold"] == "1" for p in paths)
        if has_gold:
            inpool += 1
        best_t, best_s = None, -1e30
        for p in paths:
            sc = score_path(p["text"], syls)
            path_new[(si, p["text"])] = sc
            if sc > best_s:
                best_s, best_t = sc, p["text"]
        if best_t == gold:
            gold_first += 1
            if has_gold:
                gold_first_in += 1
        if (si + 1) % 50 == 0:
            print(f"  path {si+1}", flush=True)
    t_path = time.time() - t1

    def rerank(alpha, use_v2c=False):
        corr = 0
        for si, (_, gold) in enumerate(cases):
            best_t, best_s = None, -1e30
            for p in nbest.get(si, []):
                walk = float(p["walk_score"])
                ns = path_new[(si, p["text"])]
                if use_v2c:
                    s = walk + 0.75 * float(p["v2c_score"]) + alpha * ns
                else:
                    s = walk + alpha * ns
                if s > best_s:
                    best_s, best_t = s, p["text"]
            if best_t == gold:
                corr += 1
        return corr

    alphas = [0.0, 0.1, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0]
    grid3a = [(a, rerank(a, False)) for a in alphas]
    grid3b = [(a, rerank(a, True)) for a in alphas]
    best3a = max(grid3a, key=lambda x: x[1])
    best3b = max(grid3b, key=lambda x: x[1])

    def split_half(use_v2c, n_rep=20):
        rng = random.Random(0)
        wins = 0
        bnets = []
        ships_ok = [ships[i]["correct"] == "1" for i in range(537)]
        for _ in range(n_rep):
            ids = list(range(537))
            rng.shuffle(ids)
            A, B = set(ids[:268]), set(ids[268:])
            best_a, best_c = 0.0, -1
            for a in alphas:
                c = 0
                for si in A:
                    paths = nbest.get(si, [])
                    bt, bs = None, -1e30
                    for p in paths:
                        walk = float(p["walk_score"])
                        ns = path_new[(si, p["text"])]
                        s = (
                            walk + 0.75 * float(p["v2c_score"]) + a * ns
                            if use_v2c
                            else walk + a * ns
                        )
                        if s > bs:
                            bs, bt = s, p["text"]
                    if bt == cases[si][1]:
                        c += 1
                if c > best_c:
                    best_c, best_a = c, a
            cB = shipB = 0
            for si in B:
                if ships_ok[si]:
                    shipB += 1
                paths = nbest.get(si, [])
                bt, bs = None, -1e30
                for p in paths:
                    walk = float(p["walk_score"])
                    ns = path_new[(si, p["text"])]
                    s = (
                        walk + 0.75 * float(p["v2c_score"]) + best_a * ns
                        if use_v2c
                        else walk + best_a * ns
                    )
                    if s > bs:
                        bs, bt = s, p["text"]
                if bt == cases[si][1]:
                    cB += 1
            net = cB - shipB
            bnets.append(net)
            if net > 0:
                wins += 1
        return {
            "win_rate": wins / n_rep,
            "mean_B_net": sum(bnets) / n_rep,
            "median_B_net": sorted(bnets)[n_rep // 2],
        }

    print(f"{tag} split-half...", flush=True)
    sh3a = split_half(False)
    sh3b = split_half(True)

    # neighbors for 3a
    a_star = best3a[0]
    ai = alphas.index(a_star)
    neighbors = [grid3a[j] for j in range(max(0, ai - 1), min(len(alphas), ai + 2)) if j != ai]

    # --- confusion-pattern splits for shipping errors vs best 3a/3b ---
    def conf_super(label: str) -> str:
        if label.startswith("single_char_swap"):
            return "single_char_swap"
        if label.startswith("multi_char_swap"):
            return "multi_char_swap"
        if label.startswith(
            ("homophone_", "particle_", "pronoun_", "measure_")
        ):
            return "homophone_family"
        return label.split("(")[0]

    def classify_a_local(gold: str, pred: str) -> str:
        if gold == pred:
            return "none"
        g_chars, p_chars = list(gold), list(pred)
        if len(g_chars) == len(p_chars):
            diffs = [(gc, pc) for gc, pc in zip(g_chars, p_chars) if gc != pc]
            if len(diffs) == 1:
                gc, pc = diffs[0]
                pair = f"{pc}→{gc}"
                if {gc, pc} <= set("的得地"):
                    return f"particle_的得地({pair})"
                if {gc, pc} <= set("在再"):
                    return f"particle_在再({pair})"
                if {gc, pc} <= set("他她它"):
                    return f"pronoun_他她它({pair})"
                if {gc, pc} <= set("做作坐座"):
                    return f"homophone_做作坐座({pair})"
                if {gc, pc} <= set("是事市世士"):
                    return f"homophone_是事市({pair})"
                measures = set("個支隻枝條張片本把杯碗台臺輛架")
                if gc in measures or pc in measures:
                    return f"measure_word({pair})"
                return f"single_char_swap({pair})"
            if 2 <= len(diffs) <= 3:
                return f"multi_char_swap(n={len(diffs)})"
            return f"same_len_many_diff(n={len(diffs)})"
        if abs(len(g_chars) - len(p_chars)) <= 2:
            return "len_diff_seg_or_phrase"
        return "len_diff_other"

    def pick_text(si, alpha, use_v2c):
        best_t, best_s = None, -1e30
        for p in nbest.get(si, []):
            walk = float(p["walk_score"])
            ns = path_new[(si, p["text"])]
            s = (
                walk + 0.75 * float(p["v2c_score"]) + alpha * ns
                if use_v2c
                else walk + alpha * ns
            )
            if s > best_s:
                best_s, best_t = s, p["text"]
        return best_t

    def pattern_split(alpha, use_v2c):
        # count shipping wrong sentences by pattern; how many fixed / broke
        base_wrong = defaultdict(int)
        rescued = defaultdict(int)
        broken = defaultdict(int)
        for si, (_, gold) in enumerate(cases):
            ship_ok = ships[si]["correct"] == "1"
            gip = ships[si].get("gold_in_pool", "0") == "1"
            pred_new = pick_text(si, alpha, use_v2c)
            new_ok = pred_new == gold
            if not ship_ok:
                if gip:
                    lab = conf_super(classify_a_local(gold, ships[si]["pred"]))
                else:
                    lab = "B_out_of_pool"
                base_wrong[lab] += 1
                if new_ok:
                    rescued[lab] += 1
            elif ship_ok and not new_ok:
                # regression: classify by new error pattern vs gold
                if ships[si].get("gold_in_pool", "0") == "1":
                    lab = conf_super(classify_a_local(gold, pred_new or ""))
                else:
                    lab = "B_out_of_pool"
                broken[lab] += 1
        return {
            "base_wrong": dict(base_wrong),
            "rescued": dict(rescued),
            "broken": dict(broken),
            "net_by_pattern": {
                k: rescued.get(k, 0) - broken.get(k, 0)
                for k in set(base_wrong) | set(rescued) | set(broken)
            },
        }

    conf3a = pattern_split(best3a[0], False)
    conf3b = pattern_split(best3b[0], True)
    print(
        f"{tag} conf3a single_char_swap base={conf3a['base_wrong'].get('single_char_swap',0)} "
        f"rescued={conf3a['rescued'].get('single_char_swap',0)} "
        f"broken={conf3a['broken'].get('single_char_swap',0)}",
        flush=True,
    )

    print(f"{tag} flip...", flush=True)
    t_flip0 = time.time()
    proposals = []
    for si, (readings, gold) in enumerate(cases):
        syls = [s for s in readings.split("-") if s]
        gchars = list(gold)
        schars = list(ships[si]["pred"])
        n = min(len(syls), len(gchars), len(schars))
        for i in range(n):
            if (si, i) in EXCL:
                continue
            rd = syls[i]
            cands = r2c.get(rd, [])
            if not cands:
                continue
            logits = forward_logits(schars[:n], i, rd)
            ship_id = char2id.get(schars[i], char2id["<unk>"])
            for c in cands:
                if c == schars[i]:
                    continue
                cid = char2id.get(c, char2id["<unk>"])
                delta = float(logits[cid] - logits[ship_id])
                after = schars[:n]
                after[i] = c
                after_text = "".join(after) + (
                    "".join(gchars[n:]) if len(gchars) > n else ""
                )
                proposals.append(
                    (
                        si,
                        delta,
                        ships[si]["correct"] == "1",
                        after_text == gold,
                        ships[si].get("gold_in_pool", "0") == "1",
                    )
                )
    t_flip = time.time() - t_flip0

    def flip_eval(dmin):
        by = defaultdict(list)
        for si, delta, was, now, gip in proposals:
            if delta >= dmin and delta > 0:
                by[si].append((delta, was, now, gip))
        res = reg = ra = rb = 0
        for si in range(537):
            if si not in by:
                continue
            best = max(by[si], key=lambda x: x[0])
            was, now, gip = best[1], best[2], best[3]
            if not was and now:
                res += 1
                if gip:
                    ra += 1
                else:
                    rb += 1
            elif was and not now:
                reg += 1
        return {
            "dmin": dmin,
            "net": res - reg,
            "rescue": res,
            "regress": reg,
            "final": 387 + res - reg,
            "rescue_a": ra,
            "rescue_b": rb,
        }

    flip_grid = [flip_eval(d) for d in [0, 0.5, 1, 1.5, 2, 3, 5]]
    best_flip = max(flip_grid, key=lambda x: x["net"])

    def flip_sh(n_rep=20):
        rng = random.Random(1)
        wins = 0
        bnets = []
        for _ in range(n_rep):
            ids = list(range(537))
            rng.shuffle(ids)
            A, B = set(ids[:268]), set(ids[268:])
            best_d, best_net = 0, -999
            for d in [0, 0.5, 1, 1.5, 2, 3, 5]:
                by = defaultdict(list)
                for si, delta, was, now, gip in proposals:
                    if si in A and delta >= d and delta > 0:
                        by[si].append((delta, was, now))
                res = reg = 0
                for si in A:
                    if si not in by:
                        continue
                    b = max(by[si], key=lambda x: x[0])
                    if not b[1] and b[2]:
                        res += 1
                    elif b[1] and not b[2]:
                        reg += 1
                if res - reg > best_net:
                    best_net, best_d = res - reg, d
            by = defaultdict(list)
            for si, delta, was, now, gip in proposals:
                if si in B and delta >= best_d and delta > 0:
                    by[si].append((delta, was, now))
            res = reg = 0
            for si in B:
                if si not in by:
                    continue
                b = max(by[si], key=lambda x: x[0])
                if not b[1] and b[2]:
                    res += 1
                elif b[1] and not b[2]:
                    reg += 1
            net = res - reg
            bnets.append(net)
            if net > 0:
                wins += 1
        return {
            "win_rate": wins / n_rep,
            "mean_B_net": sum(bnets) / n_rep,
            "median_B_net": sorted(bnets)[n_rep // 2],
        }

    sh_flip = flip_sh()

    # flip pattern split at best_flip dmin (among shipping-wrong rescues)
    def flip_pattern(dmin):
        by = defaultdict(list)
        for si, delta, was, now, gip in proposals:
            if delta >= dmin and delta > 0:
                by[si].append((delta, was, now, gip))
        rescued = defaultdict(int)
        broken = defaultdict(int)
        base_wrong = defaultdict(int)
        for si, (_, gold) in enumerate(cases):
            ship_ok = ships[si]["correct"] == "1"
            gip = ships[si].get("gold_in_pool", "0") == "1"
            if not ship_ok:
                if gip:
                    lab = conf_super(classify_a_local(gold, ships[si]["pred"]))
                else:
                    lab = "B_out_of_pool"
                base_wrong[lab] += 1
            if si not in by:
                continue
            best = max(by[si], key=lambda x: x[0])
            was, now, gip_f = best[1], best[2], best[3]
            if not was and now:
                if gip_f:
                    lab = conf_super(classify_a_local(gold, ships[si]["pred"]))
                else:
                    lab = "B_out_of_pool"
                rescued[lab] += 1
            elif was and not now:
                broken["was_correct"] += 1
        return {
            "base_wrong": dict(base_wrong),
            "rescued": dict(rescued),
            "broken": dict(broken),
        }

    conf_flip = flip_pattern(best_flip["dmin"])

    out = {
        "tag": tag,
        "g1_pos_acc": g1_ok / g1_n,
        "g1": f"{g1_ok}/{g1_n}",
        "g2_pos_acc": g2_ok / g2_n,
        "g2": f"{g2_ok}/{g2_n}",
        "path_rank_all": gold_first / 537,
        "path_rank_inpool": gold_first_in / max(inpool, 1),
        "path_rank_inpool_n": f"{gold_first_in}/{inpool}",
        "grid3a": grid3a,
        "grid3b": grid3b,
        "best3a": best3a,
        "best3b": best3b,
        "neighbors_3a": neighbors,
        "sh3a": sh3a,
        "sh3b": sh3b,
        "conf3a": conf3a,
        "conf3b": conf3b,
        "conf_flip": conf_flip,
        "best_flip": best_flip,
        "flip_grid": flip_grid,
        "sh_flip": sh_flip,
        "frag": f"{frag_ok}/{frag_n}",
        "free": f"{free_ok}/{free_n}",
        "latency_path_s": t_path,
        "latency_path_ms": t_path / 537 * 1000,
        "latency_flip_s": t_flip,
        "nparam": ckpt.get("nparam"),
        "val_acc": ckpt.get("val_acc"),
        "baseline_A": BASE_A,
        "baseline_B": BASE_B,
        "elapsed_total_s": time.time() - t0,
    }
    (OUT / f"eval_{tag}.json").write_text(
        json.dumps(out, indent=2, default=str), encoding="utf-8"
    )
    with (OUT / f"positions_{tag}.tsv").open("w", encoding="utf-8") as fo:
        fo.write(
            "sent_idx\tpos\treading\tgold\tship\tg1_pred\tg1_ok\tg2_pred\tg2_ok\tH\tgold_rank\tgold_in_pool\n"
        )
        for r in rows:
            fo.write("\t".join(map(str, r)) + "\n")
    # summary without huge grids in print
    summary = {k: v for k, v in out.items() if k not in ("grid3a", "grid3b", "flip_grid")}
    print(json.dumps(summary, indent=2, default=str))
    return out


if __name__ == "__main__":
    import sys

    tag = sys.argv[1] if len(sys.argv) > 1 else "clean"
    ckpt = OUT / f"model-{tag}" / "best.pt"
    print(f"eval {ckpt}", flush=True)
    eval_ckpt(ckpt, tag)
