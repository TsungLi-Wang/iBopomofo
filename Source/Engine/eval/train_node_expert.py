#!/usr/bin/env python3
# 訓練節點層封閉集合打分器：P(候選 | 讀音, 節點當下看得到的東西)。
#
# ⚠️ 這不是 next-char LM，也不是路徑重排器。輸入是**一個 walk 節點**：
# 它的讀音、引擎給的候選（含 unigram 分數與 PMI）、walk 決定的左右詞與左右字、
# 右邊是不是空的。輸出是候選上的分數，softmax 只在這個節點的候選集合上做。
#
# 樣本由 `node_sample_extract`（真的跑 walk）產生 —— 不是拿金標句子切字窗湊的。
#
# 硬規則：
#   * 讀音含 ㄉㄜ˙ 的節點一律不進訓練（PTT 標籤髒，dead-ends D）
#   * 金標不在候選裡的節點丟掉（lattice-miss，不訓練模型去選不合法的字）
#   * 分層採樣：按「讀音 × 金標值」，不是按自然字頻，否則永遠選高頻同音
#   * 難例（引擎選錯、金標仍在候選裡）要加權，否則模型只會學複製引擎
#   * τ 只在 held-out（split=dev）上定，不准看考卷或兩份真實驗證集

import argparse
import collections
import json
import math
import os
import random
import time

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

DE_READING = 'ㄉㄜ˙'
CTX_CHARS = 6      # 左右各看幾個 walk 字（當特徵，不是預測單位）
CAND_CHARS = 4     # 候選值取前幾個字
MAX_CANDS = 24     # 一個節點最多看幾個候選（按 unigram 分數取前 N）
PAD, UNK = 0, 1


class NodeExpert(nn.Module):
    """小分類器：上下文編一次，候選逐個打分，softmax 限制在候選集合上。

    刻意做小、做淺：它要在 walk 之後、打字當下跑，而且只在白名單讀音的節點上
    被呼叫。體積上限 1GB 是天花板不是目標 —— 只有證明「節點任務欠擬合」
    才准加大。
    """

    def __init__(self, n_char, n_syl, emb=128, syl_emb=64, hid=256):
        super().__init__()
        self.cfg = dict(n_char=n_char, n_syl=n_syl, emb=emb, syl_emb=syl_emb,
                        hid=hid)
        self.char_emb = nn.Embedding(n_char, emb, padding_idx=0)
        self.syl_emb = nn.Embedding(n_syl, syl_emb, padding_idx=0)
        ctx_in = emb * CTX_CHARS * 2 + syl_emb + 1
        self.ctx = nn.Sequential(nn.Linear(ctx_in, hid), nn.GELU(),
                                 nn.Linear(hid, hid))
        # 候選：值的字元 + 三個引擎特徵（unigram、PMI 左、PMI 右）+ 是否 walk 選的
        cand_in = emb * CAND_CHARS + 4
        self.cand = nn.Sequential(nn.Linear(cand_in, hid), nn.GELU(),
                                  nn.Linear(hid, hid))
        self.head = nn.Sequential(nn.Linear(hid * 2, hid), nn.GELU(),
                                  nn.Linear(hid, 1))

    def forward(self, left, right, syl, right_empty, cand_chars, cand_feats,
                cand_mask):
        b = left.shape[0]
        l = self.char_emb(left).reshape(b, -1)
        r = self.char_emb(right).reshape(b, -1)
        s = self.syl_emb(syl).sum(1)
        h = self.ctx(torch.cat([l, r, s, right_empty[:, None]], dim=-1))
        c = self.char_emb(cand_chars).reshape(b, cand_chars.shape[1], -1)
        c = self.cand(torch.cat([c, cand_feats], dim=-1))
        hx = h[:, None, :].expand(-1, c.shape[1], -1)
        logits = self.head(torch.cat([hx, c], dim=-1)).squeeze(-1)
        return logits.masked_fill(~cand_mask, -1e4)


def utf8_chars(s):
    return list(s)


def build_vocab(path, limit=0):
    chars = collections.Counter()
    syls = collections.Counter()
    with open(path, encoding='utf-8') as fh:
        next(fh)
        for i, line in enumerate(fh):
            if limit and i >= limit:
                break
            f = line.rstrip('\n').split('\t')
            if len(f) < 16:
                continue
            for s in f[6].split('-'):
                syls[s] += 1
            for field in (f[7], f[8], f[12], f[13]):
                chars.update(field)
            for c in f[15].split('|'):
                p = c.split(':')
                if p:
                    chars.update(p[0])
    itos = ['<pad>', '<unk>'] + sorted(chars)
    stos = ['<pad>', '<unk>'] + sorted(syls)
    return itos, stos


def load_rows(path, itos, stos, args):
    """讀 TSV → 張量。同時回傳每筆的分層鍵與難例旗標。"""
    ci = {c: i for i, c in enumerate(itos)}
    si = {s: i for i, s in enumerate(stos)}
    rows = []
    stats = collections.Counter()
    with open(path, encoding='utf-8') as fh:
        next(fh)
        for line in fh:
            f = line.rstrip('\n').split('\t')
            if len(f) < 16:
                stats['bad_line'] += 1
                continue
            split, kind, reading = f[1], int(f[2]), f[6]
            chosen, gold, gold_in = f[7], f[8], f[9] == '1'
            stats['total'] += 1
            if DE_READING in reading.split('-'):
                stats['drop_de'] += 1
                continue
            if not gold_in:
                stats['drop_lattice_miss'] += 1
                continue
            cands = []
            for c in f[15].split('|'):
                p = c.split(':')
                if len(p) != 5:
                    continue
                cands.append((p[0], float(p[1]), float(p[2]), float(p[3]),
                              p[4] == '1'))
            if len(cands) < 2:
                stats['drop_single_cand'] += 1
                continue
            cands.sort(key=lambda x: -x[1])
            cands = cands[:MAX_CANDS]
            gi = next((k for k, c in enumerate(cands) if c[0] == gold), -1)
            if gi < 0:
                # 金標被 MAX_CANDS 截掉了 —— 引擎其實有這個候選，但我們沒餵給
                # 模型。當成 lattice-miss 丟掉，不要製造一個「正解不在集合裡」
                # 的訓練樣本。
                stats['drop_gold_truncated'] += 1
                continue
            rows.append({
                'split': split, 'kind': kind, 'reading': reading,
                'gold': gold, 'chosen': chosen, 'gi': gi, 'cands': cands,
                'left': f[12], 'right': f[13], 'right_empty': f[14] == '1',
                'hard': chosen != gold,
            })
            stats['kept'] += 1
            if chosen != gold:
                stats['kept_hard'] += 1
            if kind == 1:
                stats['kept_prefix'] += 1
    return rows, stats, ci, si


def encode(rows, ci, si):
    n = len(rows)
    left = np.zeros((n, CTX_CHARS), dtype=np.int32)
    right = np.zeros((n, CTX_CHARS), dtype=np.int32)
    syl = np.zeros((n, 4), dtype=np.int32)
    rempty = np.zeros(n, dtype=np.float32)
    cchars = np.zeros((n, MAX_CANDS, CAND_CHARS), dtype=np.int32)
    cfeat = np.zeros((n, MAX_CANDS, 4), dtype=np.float32)
    cmask = np.zeros((n, MAX_CANDS), dtype=bool)
    gold = np.zeros(n, dtype=np.int64)
    for i, r in enumerate(rows):
        lc = utf8_chars(r['left'])[-CTX_CHARS:]
        for j, c in enumerate(lc):
            left[i, CTX_CHARS - len(lc) + j] = ci.get(c, UNK)
        rc = utf8_chars(r['right'])[:CTX_CHARS]
        for j, c in enumerate(rc):
            right[i, j] = ci.get(c, UNK)
        for j, s in enumerate(r['reading'].split('-')[:4]):
            syl[i, j] = si.get(s, UNK)
        rempty[i] = 1.0 if r['right_empty'] else 0.0
        for k, (v, u, pl, pr, walk) in enumerate(r['cands']):
            vc = utf8_chars(v)[:CAND_CHARS]
            for j, c in enumerate(vc):
                cchars[i, k, j] = ci.get(c, UNK)
            # 引擎分數縮到 O(1)：unigram 大約 -3～-12，PMI 大約 -2～2
            cfeat[i, k] = (u / 10.0, pl, pr, 1.0 if walk else 0.0)
            cmask[i, k] = True
        gold[i] = r['gi']
    return dict(left=left, right=right, syl=syl, rempty=rempty,
                cchars=cchars, cfeat=cfeat, cmask=cmask, gold=gold)


def batches(enc, idx, bs, device):
    for i in range(0, len(idx), bs):
        sel = idx[i:i + bs]
        yield (torch.from_numpy(enc['left'][sel].astype(np.int64)).to(device),
               torch.from_numpy(enc['right'][sel].astype(np.int64)).to(device),
               torch.from_numpy(enc['syl'][sel].astype(np.int64)).to(device),
               torch.from_numpy(enc['rempty'][sel]).to(device),
               torch.from_numpy(enc['cchars'][sel].astype(np.int64)).to(device),
               torch.from_numpy(enc['cfeat'][sel]).to(device),
               torch.from_numpy(enc['cmask'][sel]).to(device),
               torch.from_numpy(enc['gold'][sel]).to(device))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--nodes', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--epochs', type=int, default=6)
    ap.add_argument('--batch', type=int, default=512)
    ap.add_argument('--lr', type=float, default=2e-3)
    ap.add_argument('--hard-weight', type=int, default=6,
                    help='「引擎選錯、金標仍在候選裡」的難例重複取樣倍數')
    ap.add_argument('--per-stratum', type=int, default=400,
                    help='每個（讀音×金標值）最多留幾筆；分層採樣，不是自然字頻')
    ap.add_argument('--device', default='mps')
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    device = torch.device(args.device if (args.device != 'mps' or
                                          torch.backends.mps.is_available())
                          else 'cpu')
    itos, stos = build_vocab(args.nodes)
    rows, stats, ci, si = load_rows(args.nodes, itos, stos, args)
    print(json.dumps(dict(stats), ensure_ascii=False, indent=2))

    # ── 分層採樣：按（讀音 × 金標值）截頂 ──
    rng = random.Random(20260814)
    by_stratum = collections.defaultdict(list)
    for i, r in enumerate(rows):
        by_stratum[(r['reading'], r['gold'])].append(i)
    keep = []
    for k, v in by_stratum.items():
        if len(v) > args.per_stratum:
            v = rng.sample(v, args.per_stratum)
        keep.extend(v)
    keep.sort()
    rows = [rows[i] for i in keep]
    print(f'分層採樣後 {len(rows):,} 筆（{len(by_stratum):,} 個層）')

    enc = encode(rows, ci, si)
    is_dev = np.array([r['split'] == 'dev' for r in rows])
    is_hard = np.array([r['hard'] for r in rows])
    tr_idx = np.where(~is_dev)[0]
    dv_idx = np.where(is_dev)[0]
    hard_tr = tr_idx[is_hard[tr_idx]]
    pool = np.concatenate([tr_idx] + [hard_tr] * (args.hard_weight - 1))
    print(f'train {len(tr_idx):,}（難例 {len(hard_tr):,} ×{args.hard_weight}）'
          f' dev {len(dv_idx):,} → 每 epoch {len(pool):,}')

    model = NodeExpert(len(itos), len(stos)).to(device)
    n_params = sum(p.numel() for p in model.parameters())
    print(f'參數 {n_params:,}  fp32 {n_params * 4 / 1e6:.1f}MB  device={device}')

    opt = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=0.01)
    steps = args.epochs * math.ceil(len(pool) / args.batch)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=args.lr,
                                                total_steps=steps, pct_start=0.1)
    meta = dict(vars(args), n_params=n_params, stats=dict(stats), history=[])
    best = -1.0
    nprng = np.random.default_rng(20260814)
    for ep in range(args.epochs):
        model.train()
        order = nprng.permutation(pool)
        tot = seen = 0
        t0 = time.time()
        for *x, g in batches(enc, order, args.batch, device):
            logits = model(*x)
            loss = F.cross_entropy(logits, g)
            opt.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            sched.step()
            tot += loss.item() * len(g)
            seen += len(g)
        # dev：整體、難例（引擎選錯）、以及引擎自己的準確率當基線
        model.eval()
        agg = collections.Counter()
        with torch.no_grad():
            for i in range(0, len(dv_idx), 2048):
                sel = dv_idx[i:i + 2048]
                *x, g = next(batches(enc, sel, len(sel), device))
                pred = model(*x).argmax(1).cpu().numpy()
                gold = g.cpu().numpy()
                hard = is_hard[sel]
                agg['n'] += len(sel)
                agg['ok'] += int((pred == gold).sum())
                agg['hard_n'] += int(hard.sum())
                agg['hard_ok'] += int((pred == gold)[hard].sum())
                agg['engine_ok'] += int((~hard).sum())
        line = {'epoch': ep + 1, 'loss': tot / seen,
                'dev_acc': round(agg['ok'] / max(agg['n'], 1), 4),
                'dev_hard_acc': round(agg['hard_ok'] / max(agg['hard_n'], 1), 4),
                'engine_acc': round(agg['engine_ok'] / max(agg['n'], 1), 4),
                'sec': round(time.time() - t0)}
        meta['history'].append(line)
        print(json.dumps(line, ensure_ascii=False))
        if line['dev_acc'] > best:
            best = line['dev_acc']
            torch.save({'model': model.state_dict(), 'cfg': model.cfg,
                        'itos': itos, 'stos': stos},
                       os.path.join(args.out, 'node-expert.pt'))
            meta['best_epoch'] = ep + 1
            meta['best_dev_acc'] = best
    with open(os.path.join(args.out, 'train-meta.json'), 'w',
              encoding='utf-8') as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=2)
    print(f'best dev {best:.4f} @ epoch {meta.get("best_epoch")}')


if __name__ == '__main__':
    main()
