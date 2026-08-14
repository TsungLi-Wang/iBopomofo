#!/usr/bin/env python3
# 訓練「看注音、選同音」的節點層模型（docs/decisions/0008）。
#
# ⚠️ 這支跟 train_char_lstm_lm.py 是**不同的職位**，別混用：
#   train_char_lstm_lm.py  猜下一個漢字（現役 path-char-lstm 的來源，注音看不到）
#   本檔                   P(字 | 注音, 左右文)，在該讀音的候選集合裡打分
#
# 架構：左文 LSTM（順向）+ 右文 LSTM（逆向）+ 目標位置注音嵌入 → MLP → 對候選打分。
# 選 BiLSTM 不選 Transformer 的理由寫在 0008 第四節（C++ 推論端已有驗證過的
# LSTM 前向與 int8 反量化；增益來自目標函數＋雙向＋候選受限，不是注意力）。
#
#   .venv/bin/python Source/Engine/eval/train_node_homophone.py \
#       --data <資料目錄> --out <輸出目錄> --epochs 8

import argparse
import json
import math
import os
import time

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F


class NodeHomophoneScorer(nn.Module):
    def __init__(self, n_char, n_reading, emb=256, hidden=384, layers=2,
                 read_emb=128, merge=512, dropout=0.1):
        super().__init__()
        self.cfg = dict(n_char=n_char, n_reading=n_reading, emb=emb,
                        hidden=hidden, layers=layers, read_emb=read_emb,
                        merge=merge)
        self.char_emb = nn.Embedding(n_char, emb, padding_idx=0)
        self.read_emb = nn.Embedding(n_reading, read_emb)
        self.lstm_l = nn.LSTM(emb, hidden, layers, batch_first=True,
                              dropout=dropout if layers > 1 else 0.0)
        self.lstm_r = nn.LSTM(emb, hidden, layers, batch_first=True,
                              dropout=dropout if layers > 1 else 0.0)
        self.merge = nn.Sequential(
            nn.Linear(hidden * 2 + read_emb, merge), nn.GELU(),
            nn.Dropout(dropout), nn.Linear(merge, merge))
        self.out = nn.Linear(merge, n_char)

    def hidden_state(self, left, right, reading):
        # 左文照原順序讀到目標位置；右文反序讀回目標位置 → 兩邊都停在目標旁。
        hl = self.lstm_l(self.char_emb(left))[0][:, -1]
        hr = self.lstm_r(self.char_emb(right.flip(1)))[0][:, -1]
        return self.merge(torch.cat([hl, hr, self.read_emb(reading)], dim=-1))

    def forward(self, left, right, reading, cand_ids, cand_mask):
        h = self.hidden_state(left, right, reading)
        w = self.out.weight[cand_ids]                    # [B, C, merge]
        b = self.out.bias[cand_ids]                      # [B, C]
        logits = torch.einsum('bd,bcd->bc', h, w) + b
        return logits.masked_fill(~cand_mask, -1e4)


def load_split(path):
    z = np.load(path)
    return {k: z[k] for k in ('left', 'right', 'reading', 'target', 'kind')}


def build_cand_table(vocab, device):
    """讀音 id → 候選字 id（padded）＋ mask。候選集合完全由讀音決定。"""
    cand = vocab['cand']
    n_r = len(vocab['readings'])
    width = max(len(v) for v in cand.values())
    ids = np.zeros((n_r, width), dtype=np.int64)
    mask = np.zeros((n_r, width), dtype=bool)
    for k, v in cand.items():
        i = int(k)
        ids[i, :len(v)] = v
        mask[i, :len(v)] = True
    return (torch.from_numpy(ids).to(device), torch.from_numpy(mask).to(device))


def target_slot(cand_ids, target):
    """target 在候選列表裡的位置（受限 softmax 的答案 index）。"""
    return (cand_ids == target.unsqueeze(1)).float().argmax(dim=1)


def run_eval(model, split, cand_ids_tbl, cand_mask_tbl, device, bs=2048):
    model.eval()
    agg = {}
    with torch.no_grad():
        n = len(split['target'])
        for i in range(0, n, bs):
            sl = slice(i, i + bs)
            left = torch.from_numpy(split['left'][sl].astype(np.int64)).to(device)
            right = torch.from_numpy(split['right'][sl].astype(np.int64)).to(device)
            rd = torch.from_numpy(split['reading'][sl].astype(np.int64)).to(device)
            tg = torch.from_numpy(split['target'][sl].astype(np.int64)).to(device)
            kind = split['kind'][sl]
            cid, cmask = cand_ids_tbl[rd], cand_mask_tbl[rd]
            logits = model(left, right, rd, cid, cmask)
            pred = cid.gather(1, logits.argmax(1, keepdim=True)).squeeze(1)
            ok = (pred == tg).cpu().numpy()
            for k, label in ((0, 'main'), (1, 'aux')):
                m = kind == k
                if m.any():
                    a = agg.setdefault(label, [0, 0])
                    a[0] += int(ok[m].sum())
                    a[1] += int(m.sum())
    model.train()
    return {k: (v[0] / v[1], v[1]) for k, v in agg.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--data', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--epochs', type=int, default=8)
    ap.add_argument('--batch', type=int, default=1024)
    ap.add_argument('--lr', type=float, default=2e-3)
    ap.add_argument('--emb', type=int, default=256)
    ap.add_argument('--hidden', type=int, default=384)
    ap.add_argument('--layers', type=int, default=2)
    ap.add_argument('--main-oversample', type=int, default=10,
                    help='contexts 是主監督但只有三萬條，重複取樣讓它有份量')
    ap.add_argument('--device', default='mps')
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    device = torch.device(args.device if (args.device != 'mps' or
                                          torch.backends.mps.is_available())
                          else 'cpu')
    vocab = json.load(open(os.path.join(args.data, 'vocab.json'), encoding='utf-8'))
    train = load_split(os.path.join(args.data, 'train.npz'))
    dev = load_split(os.path.join(args.data, 'dev.npz'))
    cand_ids_tbl, cand_mask_tbl = build_cand_table(vocab, device)

    model = NodeHomophoneScorer(len(vocab['itos']), len(vocab['readings']),
                                emb=args.emb, hidden=args.hidden,
                                layers=args.layers).to(device)
    n_params = sum(p.numel() for p in model.parameters())
    print(f'參數 {n_params:,}  fp32 {n_params * 4 / 1e6:.1f}MB  '
          f'int8 約 {n_params / 1e6:.1f}MB  device={device}')

    # 主監督重複取樣：索引層面做，不複製張量。
    idx_main = np.where(train['kind'] == 0)[0]
    idx_aux = np.where(train['kind'] == 1)[0]
    order_pool = np.concatenate([np.tile(idx_main, args.main_oversample), idx_aux])
    print(f'train 主監督 {len(idx_main):,}（×{args.main_oversample}）'
          f' 輔助 {len(idx_aux):,} → 每 epoch {len(order_pool):,}')

    opt = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=0.01)
    steps = args.epochs * math.ceil(len(order_pool) / args.batch)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=args.lr,
                                                total_steps=steps,
                                                pct_start=0.1)
    best = -1.0
    rng = np.random.default_rng(20260814)
    meta = dict(vars(args), n_params=n_params, history=[])
    for ep in range(args.epochs):
        order = rng.permutation(order_pool)
        t0, tot, seen = time.time(), 0.0, 0
        for i in range(0, len(order), args.batch):
            sel = order[i:i + args.batch]
            left = torch.from_numpy(train['left'][sel].astype(np.int64)).to(device)
            right = torch.from_numpy(train['right'][sel].astype(np.int64)).to(device)
            rd = torch.from_numpy(train['reading'][sel].astype(np.int64)).to(device)
            tg = torch.from_numpy(train['target'][sel].astype(np.int64)).to(device)
            cid, cmask = cand_ids_tbl[rd], cand_mask_tbl[rd]
            logits = model(left, right, rd, cid, cmask)
            loss = F.cross_entropy(logits, target_slot(cid, tg))
            opt.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            sched.step()
            tot += loss.item() * len(sel)
            seen += len(sel)
        acc = run_eval(model, dev, cand_ids_tbl, cand_mask_tbl, device)
        line = {'epoch': ep + 1, 'loss': tot / seen,
                'dev': {k: round(v[0], 4) for k, v in acc.items()},
                'dev_n': {k: v[1] for k, v in acc.items()},
                'sec': round(time.time() - t0)}
        meta['history'].append(line)
        print(json.dumps(line, ensure_ascii=False))
        # 用「主監督 dev」挑 checkpoint —— 那是這顆模型的職位，不是輔助任務。
        score = acc.get('main', (0, 0))[0]
        if score > best:
            best = score
            torch.save({'model': model.state_dict(), 'cfg': model.cfg},
                       os.path.join(args.out, 'node-scorer.pt'))
            meta['best_dev_main'] = score
            meta['best_epoch'] = ep + 1
    with open(os.path.join(args.out, 'train-meta.json'), 'w', encoding='utf-8') as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=2)
    print(f'best dev(main) = {best:.4f} @ epoch {meta.get("best_epoch")}')


if __name__ == '__main__':
    main()
