#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Prototype-001 CLI：train / evaluate / predict。

**prototype code，不是 production code。**
不修改 production、不接輸入法、不 merge、不 enable、不跑正式 ship-gate。

    python3 -m prototype.ccd.cli train    --nodes ... --sentences ... --out ckpt.pt
    python3 -m prototype.ccd.cli evaluate --ckpt ckpt.pt --nodes ... --sentences ...
    python3 -m prototype.ccd.cli predict  --ckpt ckpt.pt --context 我今天想要 \\
                                          --right 一件事情 --reading ㄗㄨㄛˋ \\
                                          --candidates 做,作,坐,座

決策規則是純 `argmax`，**沒有 threshold**（v0.1 刻意不做 operating point）。
"""

import argparse
import json
import os
import sys
import time

import numpy as np
import torch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from prototype.ccd import data as D  # noqa: E402
from prototype.ccd.model import (CAND_FEATS, WIN,  # noqa: E402
                                 ContextualCandidateDecision, pairwise_loss)

MAX_CANDS = 32
SEED = 20260818


def featurize(samples, stoi, rtoi):
    """gold 只用來產生 gold_idx（label），**不進入任何 feature**。"""
    n = len(samples)
    left = np.zeros((n, WIN), dtype=np.int64)
    right = np.zeros((n, WIN), dtype=np.int64)
    rd = np.zeros(n, dtype=np.int64)
    cand = np.zeros((n, MAX_CANDS), dtype=np.int64)
    feats = np.zeros((n, MAX_CANDS, CAND_FEATS), dtype=np.float32)
    mask = np.zeros((n, MAX_CANDS), dtype=bool)
    gidx = np.zeros(n, dtype=np.int64)
    for i, s in enumerate(samples):
        lc = list(s["left"][-WIN:])
        lc = [D.PAD] * (WIN - len(lc)) + lc
        rc = list(s["right"][:WIN])
        rc = rc + [D.PAD] * (WIN - len(rc))
        left[i] = [stoi.get(c, 0) for c in lc]
        right[i] = [stoi.get(c, 0) for c in rc]
        rd[i] = rtoi.get(s["reading"], 0)
        cs = s["cands"][:MAX_CANDS]
        for j, c in enumerate(cs):
            cand[i, j] = stoi.get(c[0], 0)
            feats[i, j] = [c[1], c[2], c[3], 1.0 if c[4] else 0.0,
                           1.0 if s["right_empty"] else 0.0]
            mask[i, j] = True
        g = next((j for j, c in enumerate(cs) if c[0] == s["gold"]), -1)
        gidx[i] = max(g, 0)
        s["_gold_in_cap"] = g >= 0
        s["_n_cap"] = len(cs)
    return dict(left=left, right=right, reading=rd, cand=cand, feats=feats,
                mask=mask, gold=gidx)


def to_t(enc, sl=None):
    sl = slice(None) if sl is None else sl
    return (torch.from_numpy(enc["left"][sl]), torch.from_numpy(enc["right"][sl]),
            torch.from_numpy(enc["reading"][sl]), torch.from_numpy(enc["cand"][sl]),
            torch.from_numpy(enc["feats"][sl]), torch.from_numpy(enc["mask"][sl]),
            torch.from_numpy(enc["gold"][sl]))


def norm_feats(enc, mu=None, sd=None):
    f = enc["feats"]
    m = enc["mask"]
    if mu is None:
        flat = f[m]
        mu, sd = flat.mean(0), flat.std(0) + 1e-6
    enc["feats"] = ((f - mu) / sd) * m[..., None]
    return mu, sd


def cmd_train(a):
    t0 = time.time()
    torch.manual_seed(SEED)
    np.random.seed(SEED)
    samples = D.load_samples(a.nodes, a.sentences, max_rows=a.max_rows)
    tr = [s for s in samples if s["fold"] != a.dev_fold]
    dv = [s for s in samples if s["fold"] == a.dev_fold]
    print(f"樣本 {len(samples):,}（train {len(tr):,} / dev {len(dv):,}）"
          f"　dev fold = {a.dev_fold}")
    stoi, itos, rtoi, rtos = D.build_vocab(tr)
    print(f"字表 {len(itos):,}　讀音表 {len(rtos):,}")

    enc = featurize(tr, stoi, rtoi)
    mu, sd = norm_feats(enc)
    model = ContextualCandidateDecision(len(itos), len(rtos), emb=a.emb,
                                        hid=a.hid)
    npar = sum(p.numel() for p in model.parameters())
    print(f"參數量 {npar:,}")
    opt = torch.optim.Adam(model.parameters(), lr=a.lr, weight_decay=1e-5)
    N = len(tr)
    for ep in range(a.epochs):
        model.train()
        order = np.random.permutation(N)
        tot = 0.0
        nb = 0
        for i in range(0, N, a.batch):
            sl = order[i:i + a.batch]
            L, R, RD, C, F, M, G = to_t(enc, sl)
            opt.zero_grad()
            loss = pairwise_loss(model(L, R, RD, C, F, M), G, M)
            loss.backward()
            opt.step()
            tot += float(loss.detach())
            nb += 1
        print(f"  epoch {ep + 1}/{a.epochs}  loss {tot / max(nb, 1):.4f}"
              f"  ({time.time() - t0:.0f}s)")
    ck = {
        "model": model.state_dict(),
        "cfg": {"n_char": len(itos), "n_reading": len(rtos), "emb": a.emb,
                "hid": a.hid},
        "itos": itos, "rtos": rtos,
        "mu": mu.tolist(), "sd": sd.tolist(),
        "dev_fold": a.dev_fold, "seed": SEED, "max_cands": MAX_CANDS,
        "train_samples": len(tr), "params": npar,
    }
    torch.save(ck, a.out)
    print(f"checkpoint -> {a.out}"
          f"（{os.path.getsize(a.out) / 1e6:.2f} MB，{time.time() - t0:.0f}s）")


def load_ckpt(path):
    ck = torch.load(path, map_location="cpu", weights_only=False)
    m = ContextualCandidateDecision(**ck["cfg"])
    m.load_state_dict(ck["model"])
    m.eval()
    stoi = {c: i for i, c in enumerate(ck["itos"])}
    rtoi = {r: i for i, r in enumerate(ck["rtos"])}
    return m, ck, stoi, rtoi


def score_all(model, ck, stoi, rtoi, samples, batch=512, neutral_feats=False):
    """neutral_feats=True 用於手動 predict：呼叫端沒有引擎算的 unigram/PMI，
    此時把數值特徵設成訓練集平均（正規化後為 0），而不是硬塞 0
    —— 硬塞 0 正規化後會變成離群值，讓分數失真。"""
    enc = featurize(samples, stoi, rtoi)
    norm_feats(enc, np.array(ck["mu"], dtype=np.float32),
               np.array(ck["sd"], dtype=np.float32))
    if neutral_feats:
        enc["feats"][:] = 0.0
    out = np.zeros((len(samples), MAX_CANDS), dtype=np.float32)
    with torch.no_grad():
        for i in range(0, len(samples), batch):
            sl = slice(i, i + batch)
            L, R, RD, C, F, M, _ = to_t(enc, sl)
            out[sl] = model(L, R, RD, C, F, M).numpy()
    return out


def evaluate(model, ck, stoi, rtoi, samples):
    sc = score_all(model, ck, stoi, rtoi, samples)
    r = dict(n=len(samples), base_top1=0, proto_top1=0, rescue=0, damage=0,
             override=0, cand_absent=0, gold_beyond_cap=0, top2=0, top3=0,
             both_wrong=0)
    rescue_ex, damage_ex, all_ex = [], [], []
    for i, s in enumerate(samples):
        cs = s["cands"][:MAX_CANDS]
        order = np.argsort(-sc[i][:len(cs)])
        pred = cs[int(order[0])][0]
        gold, chosen = s["gold"], s["chosen"]
        if s["gold_idx"] < 0:
            r["cand_absent"] += 1
        elif not s["_gold_in_cap"]:
            r["gold_beyond_cap"] += 1
        r["base_top1"] += chosen == gold
        r["proto_top1"] += pred == gold
        for k, key in ((2, "top2"), (3, "top3")):
            r[key] += any(cs[int(j)][0] == gold for j in order[:k])
        if pred != chosen:
            r["override"] += 1
        rec = {"s": s, "pred": pred,
               "rank": [(cs[int(j)][0], float(sc[i][int(j)])) for j in order[:6]]}
        all_ex.append(rec)
        if chosen != gold and pred == gold:
            r["rescue"] += 1
            rescue_ex.append(rec)
        elif chosen == gold and pred != gold:
            r["damage"] += 1
            damage_ex.append(rec)
        elif chosen != gold and pred != gold:
            r["both_wrong"] += 1
    r["net"] = r["rescue"] - r["damage"]
    r["precision"] = r["rescue"] / r["override"] if r["override"] else float("nan")
    return r, rescue_ex, damage_ex, all_ex


def fmt_ex(rec):
    s = rec["s"]
    rk = " ".join(f"{c}:{v:.2f}" for c, v in rec["rank"])
    tag = ("RESCUE" if s["chosen"] != s["gold"] and rec["pred"] == s["gold"]
           else "DAMAGE" if s["chosen"] == s["gold"] and rec["pred"] != s["gold"]
           else "KEEP-OK" if s["chosen"] == s["gold"] else "BOTH-WRONG")
    return (f'  ctx: {s["left"][-6:]}[?]{s["right"][:6]}\n'
            f'  reading: {s["reading"]}   cands: '
            f'{"/".join(c[0] for c in s["cands"][:8])}\n'
            f'  engine: {s["chosen"]}   proto: {rec["pred"]}   gold: {s["gold"]}'
            f'   -> {tag}\n'
            f'  proto ranking: {rk}\n')


def cmd_evaluate(a):
    t0 = time.time()
    model, ck, stoi, rtoi = load_ckpt(a.ckpt)
    samples = D.load_samples(a.nodes, a.sentences, max_rows=a.max_rows)
    dv = [s for s in samples if s["fold"] == ck["dev_fold"]]
    print(f"held-out fold {ck['dev_fold']}：{len(dv):,} 個節點"
          f"（文件級切分，與訓練不重疊）")
    r, resc, dmg, allx = evaluate(model, ck, stoi, rtoi, dv)
    n = r["n"]
    print(f"\n| 指標 | R4 / 現行引擎 | Prototype-001 |")
    print("|---|---:|---:|")
    print(f"| top-1 accuracy | {r['base_top1']/n:.4f} | {r['proto_top1']/n:.4f} |")
    print(f"| top-2 accuracy | — | {r['top2']/n:.4f} |")
    print(f"| top-3 accuracy | — | {r['top3']/n:.4f} |")
    print(f"| rescue | — | {r['rescue']:,} |")
    print(f"| damage | — | {r['damage']:,} |")
    print(f"| **net** | — | **{r['net']:+,}** |")
    print(f"| precision | — | {r['precision']:.4f} |")
    print(f"| override | — | {r['override']:,} |")
    print(f"| candidate_absent | {r['cand_absent']:,} | 同左（不負責救）|")
    print(f"| gold 超出 MAX_CANDS={MAX_CANDS} | {r['gold_beyond_cap']:,} | 同左 |")
    print(f"\n推論耗時 {time.time() - t0:.1f}s（含載入）")
    if a.dump:
        with open(a.dump, "w", encoding="utf-8") as fh:
            json.dump({"metrics": r,
                       "rescue": [fmt_ex(x) for x in resc[:a.examples]],
                       "damage": [fmt_ex(x) for x in dmg[:a.examples]],
                       "demo": [fmt_ex(x) for x in allx[:a.examples]]},
                      fh, ensure_ascii=False, indent=1)
        print(f"範例 -> {a.dump}")
    print(f"\n=== RESCUE 範例（最多 {a.examples}）===")
    for x in resc[:a.examples]:
        print(fmt_ex(x))
    print(f"\n=== DAMAGE 範例（最多 {a.examples}）===")
    for x in dmg[:a.examples]:
        print(fmt_ex(x))


def cmd_predict(a):
    model, ck, stoi, rtoi = load_ckpt(a.ckpt)
    cands = [(c, 0.0, 0.0, 0.0, False) for c in a.candidates.split(",") if c]
    if not cands:
        print("錯誤：--candidates 至少要有一個候選", file=sys.stderr)
        return 2
    s = {"left": a.context, "right": a.right, "reading": a.reading,
         "right_empty": not a.right, "chosen": cands[0][0],
         "gold": a.gold or cands[0][0], "cands": cands, "gold_idx": 0}
    sc = score_all(model, ck, stoi, rtoi, [s], neutral_feats=True)[0][:len(cands)]
    order = np.argsort(-sc)
    print(f'Context:\n  {a.context}[?]{a.right}\nReading:\n  {a.reading}')
    print("Candidates:\n  " + " / ".join(c[0] for c in cands))
    print("Prototype:")
    ex = np.exp(sc - sc.max())
    p = ex / ex.sum()
    for j in order:
        print(f"  {cands[int(j)][0]}  {p[int(j)]:.3f}  (raw {sc[int(j)]:+.3f})")
    print(f"Top-1: {cands[int(order[0])][0]}")
    print("（注意：手動 predict 沒有引擎算的 unigram/PMI，數值特徵以訓練集平均代入，"
          "\n  因此只反映『脈絡 × 候選』這一半的訊號，與 evaluate 的完整條件不同。）")
    return 0


def main():
    ap = argparse.ArgumentParser(
        prog="prototype.ccd.cli",
        description="Prototype-001 Contextual Candidate Decision（研究用，非 production）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    t = sub.add_parser("train", help="訓練並輸出 checkpoint")
    t.add_argument("--nodes", required=True)
    t.add_argument("--sentences", required=True)
    t.add_argument("--out", required=True)
    t.add_argument("--dev-fold", type=int, default=0)
    t.add_argument("--epochs", type=int, default=3)
    t.add_argument("--batch", type=int, default=256)
    t.add_argument("--lr", type=float, default=1e-3)
    t.add_argument("--emb", type=int, default=64)
    t.add_argument("--hid", type=int, default=128)
    t.add_argument("--max-rows", type=int, default=0, help="0 = 全部")
    t.set_defaults(fn=cmd_train)

    e = sub.add_parser("evaluate", help="在 held-out fold 上評估並列出範例")
    e.add_argument("--ckpt", required=True)
    e.add_argument("--nodes", required=True)
    e.add_argument("--sentences", required=True)
    e.add_argument("--max-rows", type=int, default=0)
    e.add_argument("--examples", type=int, default=20)
    e.add_argument("--dump", default="")
    e.set_defaults(fn=cmd_evaluate)

    p = sub.add_parser("predict", help="對單一節點打分")
    p.add_argument("--ckpt", required=True)
    p.add_argument("--context", default="", help="左側脈絡")
    p.add_argument("--right", default="", help="右側脈絡")
    p.add_argument("--reading", required=True)
    p.add_argument("--candidates", required=True, help="逗號分隔")
    p.add_argument("--gold", default="")
    p.set_defaults(fn=cmd_predict)

    a = ap.parse_args()
    for f in ("nodes", "sentences", "ckpt"):
        v = getattr(a, f, None)
        if v and not os.path.exists(v):
            print(f"錯誤：--{f} 找不到檔案：{v}", file=sys.stderr)
            return 2
    return a.fn(a) or 0


if __name__ == "__main__":
    sys.exit(main())
