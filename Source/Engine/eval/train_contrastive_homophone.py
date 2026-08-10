#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""train_contrastive_homophone.py — 路線 C：同音字對比微調

拿現役的 v2c，**只動同音字那幾個字的權重**，訓練目標從「這句順不順」
改成「這兩三個同音字，哪個放進去整句最合理」。

## 最小手術：只解凍 9 個字的參數

    可訓練 = emb.weight[那幾個字] ＋ fc.weight[那幾個字] ＋ fc.bias[那幾個字]

其餘全部凍結。這是刻意的：

* **emb 那幾列** 決定「選了這個字之後，後面的字怎麼被條件化」——
  這是模型分辨「跑得很快 vs 跑的很快」的唯一管道（因果模型看不到右邊，
  只能靠選字影響後續預測）。
* **fc 那幾列** 決定「在這個上下文，這個字有多可能」。
* 其他字一列都不動 → 模型對非同音字位置的行為幾乎不變，
  出事的範圍被限制在這 9 個字上。

參數量：9 字 × (256 emb + 512 fc + 1 bias) ≈ **7 千個**，佔全模型 0.07%。

## 損失：整句對比，不是單點分類

把整句用每個候選字各算一次 log-prob 總和，對這幾個分數做 softmax，
要正解那個最大。**單點分類學不到右邊的訊號**（因果模型在目標位置還沒看到右邊）。

## 不給頻率資訊

訓練資料是平衡取樣的（每個候選字當正解的筆數相同），所以模型無法從
資料分布學到「在比再常見」。那正是路線 A 在推論時要拿掉的東西。

⚠️ **動手前先跑 `--steps 0`**，確認匯出的模型跟原檔逐位元組相同 ——
沒有這個對照，之後量到的差異分不清是訓練還是 I/O 造成的。

用法：
    python3 train_contrastive_homophone.py \\
        --model models/path-char-lstm-spoken-v2c.bin \\
        --data /tmp/rc-data -o /tmp/v2d.bin --epochs 2
"""

import argparse
import json
import os
import random
import sys
import time
from pathlib import Path

import torch
import torch.nn.functional as F

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lwlstm_io import load as load_model, save as save_model  # noqa: E402


def read_jsonl(path):
    with open(path, encoding="utf-8") as fh:
        return [json.loads(l) for l in fh if l.strip()]


def encode(sent, stoi, unk):
    return [stoi.get(c, unk) for c in sent]


def batch_scores(model, rows, stoi, unk, device):
    """回傳 [B, C]：每筆資料、每個候選字，整句的 log-prob 總和。

    做法是把「同一句換不同候選字」當成不同樣本一起丟進去，算完再收攏。
    句子補到同長度，計分時用 mask 把 padding 排除。
    """
    seqs, owner, slot = [], [], []
    for bi, r in enumerate(rows):
        for ci, cand in enumerate(r["candidates"]):
            s = list(r["sentence"])
            s[r["target_index"]] = cand
            seqs.append(encode("".join(s), stoi, unk))
            owner.append(bi)
            slot.append(ci)
    maxlen = max(len(s) for s in seqs)
    x = torch.full((len(seqs), maxlen), unk, dtype=torch.long)
    mask = torch.zeros((len(seqs), maxlen), dtype=torch.bool)
    for i, s in enumerate(seqs):
        x[i, :len(s)] = torch.tensor(s, dtype=torch.long)
        mask[i, :len(s)] = True
    x, mask = x.to(device), mask.to(device)

    logits = model(x)                                   # [N, T, V]
    logp = F.log_softmax(logits[:, :-1, :], dim=-1)     # 預測下一個字
    tgt = x[:, 1:]
    step = logp.gather(-1, tgt.unsqueeze(-1)).squeeze(-1)   # [N, T-1]
    step = step * mask[:, 1:].float()
    total = step.sum(dim=1)                             # 每個序列的 log-prob 總和

    ncand = len(rows[0]["candidates"])
    assert all(len(r["candidates"]) == ncand for r in rows), \
        "同一批的候選數必須一致 —— 請用 make_batches() 分批"
    out = torch.full((len(rows), ncand), float("-inf"), device=device)
    out[torch.tensor(owner, device=device),
        torch.tensor(slot, device=device)] = total
    return out


def make_batches(rows, bs, rng=None):
    """依組分桶再切批。

    ⚠️ 不能直接對混合資料切批：同一批的候選數必須一致（在再 2 個、吧八巴 3 個），
    否則收攏成矩陣時會越界。第一版沒分桶，結果幾乎每批都含吧八巴而被整批跳過，
    等於沒訓練到 —— 而且從輸出看不出來（loss 照印，只是步數對不上）。
    """
    buckets = {}
    for r in rows:
        buckets.setdefault(r["group"], []).append(r)
    out = []
    for items in buckets.values():
        if rng:
            rng.shuffle(items)
        for k in range(0, len(items), bs):
            out.append(items[k:k + bs])
    if rng:
        rng.shuffle(out)
    return out


def evaluate(model, rows, stoi, unk, device, bs):
    model.eval()
    ok = tot = 0
    per = {}
    with torch.no_grad():
        for chunk in make_batches(rows, bs):
            scores = batch_scores(model, chunk, stoi, unk, device)
            pick = scores.argmax(dim=1).tolist()
            for r, p in zip(chunk, pick):
                got = r["candidates"][p]
                gold = r["gold"]
                d = per.setdefault(gold, [0, 0])
                d[1] += 1
                tot += 1
                if got == gold:
                    ok += 1
                    d[0] += 1
    model.train()
    return ok / max(tot, 1), per


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--data", required=True, help="build_contrastive_data.py 的輸出目錄")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--epochs", type=int, default=2)
    ap.add_argument("--batch", type=int, default=24)
    ap.add_argument("--lr", type=float, default=0.02)
    ap.add_argument("--steps", type=int, default=-1,
                    help="只跑幾步（除錯用）。**0 = 完全不訓練**，"
                         "用來驗證匯出的模型跟原檔逐位元組相同")
    ap.add_argument("--mine-hard", type=float, default=0.0,
                    help="難例挖掘：先用**原始模型**掃過訓練集，只留下"
                         "『答錯』或『正解與次高的分差小於這個值』的句子。"
                         "0 = 不挖掘（用全部資料）。建議 3.0。\n"
                         "為什麼需要：語料句大多是送分題，v2c 本來就對 95.7%，"
                         "拿它們訓練等於一直教模型它已經會的東西 —— "
                         "實測全量訓練會讓分數不升反降。難的那些才有訊號。")
    ap.add_argument("--device", default="mps")
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    torch.manual_seed(args.seed)
    random.seed(args.seed)
    model, itos, meta = load_model(args.model)
    stoi = {c: i for i, c in enumerate(itos)}
    unk = stoi.get("　", 0)

    rng = random.Random(args.seed)
    train, dev = [], []
    for p in sorted(Path(args.data).glob("*.train.jsonl")):
        train += read_jsonl(p)
    for p in sorted(Path(args.data).glob("*.dev.jsonl")):
        dev += read_jsonl(p)
    rng.shuffle(dev)   # dev 是按組串起來的，不打亂的話 dev[:2000] 只有一組
    if not train:
        sys.exit(f"{args.data} 裡沒有 *.train.jsonl")

    # 要解凍的字：訓練資料裡出現過的所有候選字
    targets = sorted({c for r in train for c in r["candidates"]})
    missing = [c for c in targets if c not in stoi]
    if missing:
        sys.exit(f"這些字不在模型詞表裡：{''.join(missing)}")
    tid = torch.tensor([stoi[c] for c in targets], dtype=torch.long)
    print(f"訓練 {len(train)} 筆、驗證 {len(dev)} 筆")
    print(f"解凍 {len(targets)} 個字：{''.join(targets)}")

    device = torch.device(args.device if args.device != "mps"
                          or torch.backends.mps.is_available() else "cpu")
    model.to(device).train()
    for p in model.parameters():
        p.requires_grad_(False)
    for name in ("emb.weight", "fc.weight", "fc.bias"):
        dict(model.named_parameters())[name].requires_grad_(True)
    tid_dev = tid.to(device)
    n_trainable = len(targets) * (meta["emb"] + meta["hidden"] + 1)
    print(f"實際會更新的參數：{n_trainable} 個"
          f"（全模型的 {n_trainable / 9.73e6 * 100:.3f}%）")

    params = [dict(model.named_parameters())[n]
              for n in ("emb.weight", "fc.weight", "fc.bias")]
    opt = torch.optim.Adam(params, lr=args.lr)

    def mask_grads():
        """把非目標字的梯度歸零 —— 這是「只動那幾個字」的實作方式。

        直接對 Parameter 的切片做 requires_grad 是不行的（PyTorch 只支援
        整個 tensor），所以改成每步把其他列的梯度清掉。
        """
        for p in params:
            if p.grad is None:
                continue
            keep = torch.zeros_like(p.grad)
            keep[tid_dev] = p.grad[tid_dev]
            p.grad.copy_(keep)

    if args.steps == 0:
        print("\n--steps 0：完全不訓練，直接匯出（對照組）")
        save_model(args.out, model.cpu(), itos, meta)
        same = Path(args.out).read_bytes() == Path(args.model).read_bytes()
        print("✅ 與原檔逐位元組相同" if same else "❌ 與原檔不同 —— 匯出有問題")
        return 0 if same else 1

    if args.mine_hard > 0:
        t_mine = time.time()
        kept = []
        model.eval()
        with torch.no_grad():
            for chunk in make_batches(train, args.batch):
                sc = batch_scores(model, chunk, stoi, unk, device)
                top2 = sc.topk(2, dim=1)
                for bi, r in enumerate(chunk):
                    gi = r["candidates"].index(r["gold"])
                    gold_s = sc[bi, gi].item()
                    best_i = top2.indices[bi, 0].item()
                    rival = (top2.values[bi, 1].item() if best_i == gi
                             else top2.values[bi, 0].item())
                    if best_i != gi or (gold_s - rival) < args.mine_hard:
                        kept.append(r)
        model.train()
        print(f"難例挖掘：{len(train)} → {len(kept)} 筆"
              f"（{len(kept) * 100 / len(train):.1f}%，{time.time() - t_mine:.0f}s）")
        bal = {}
        for r in kept:
            bal.setdefault((r["group"], r["gold"]), []).append(r)
        n = {}
        for (g, c), v in bal.items():
            n.setdefault(g, []).append(len(v))
        train = []
        for (g, c), v in bal.items():
            rng.shuffle(v)
            train += v[:min(n[g])]
        print(f"重新平衡後 {len(train)} 筆"
              f"（{' '.join(f'{g}:{min(v)}/字' for g, v in sorted(n.items()))}）")
        if not train:
            sys.exit("挖不到難例 —— 門檻調低或關掉 --mine-hard")

    acc0, per0 = evaluate(model, dev[:2000], stoi, unk, device, args.batch)
    print(f"\n訓練前 dev 正確率 {acc0 * 100:.1f}%"
          f"（{' '.join(f'{k}:{v[0] * 100 // max(v[1], 1)}%' for k, v in sorted(per0.items()))}）")

    step = 0
    t0 = time.time()
    for ep in range(args.epochs):
        run = 0.0
        for chunk in make_batches(train, args.batch, rng):
            scores = batch_scores(model, chunk, stoi, unk, device)
            gold = torch.tensor([r["candidates"].index(r["gold"]) for r in chunk],
                                device=device)
            loss = F.cross_entropy(scores, gold)
            opt.zero_grad(set_to_none=True)
            loss.backward()
            mask_grads()
            opt.step()
            run += loss.item()
            step += 1
            if args.steps > 0 and step >= args.steps:
                break
            if step % 200 == 0:
                print(f"  ep{ep + 1} step {step} loss {run / 200:.4f} "
                      f"({time.time() - t0:.0f}s)")
                run = 0.0
        if args.steps > 0 and step >= args.steps:
            break
        acc, per = evaluate(model, dev[:2000], stoi, unk, device, args.batch)
        print(f"ep{ep + 1} 結束 dev 正確率 {acc * 100:.1f}%"
              f"（{' '.join(f'{k}:{v[0] * 100 // max(v[1], 1)}%' for k, v in sorted(per.items()))}）")

    acc1, per1 = evaluate(model, dev, stoi, unk, device, args.batch)
    print(f"\n最終 dev（全部 {len(dev)} 筆）正確率 {acc1 * 100:.1f}%")
    for k, v in sorted(per1.items()):
        print(f"  {k}: {v[0]}/{v[1]} = {v[0] * 100 / max(v[1], 1):.1f}%")
    save_model(args.out, model.cpu(), itos, meta)
    print(f"\n寫出 {args.out}")
    print("※ 這是語料 dev 的分數，不是 EX1166。要知道對引擎的實際效果，"
          "得用評分機跑對照實驗。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
