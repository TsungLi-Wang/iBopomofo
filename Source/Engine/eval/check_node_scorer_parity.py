#!/usr/bin/env python3
# C++（NodeHomophoneScorer）與 PyTorch（train_node_homophone）逐題同分檢查。
# 由 scripts/node-scorer-parity.sh 呼叫；為什麼要有這道關卡寫在那支裡。

import argparse
import json
import os
import subprocess
import sys

import numpy as np
import torch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from train_node_homophone import NodeHomophoneScorer, build_cand_table  # noqa: E402

TOL = 2e-3   # log-softmax 上的絕對差；float32 逐步累加的重排誤差量級


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--probe', required=True)
    ap.add_argument('--model', required=True)
    ap.add_argument('--data', required=True)
    ap.add_argument('--ckpt', required=True)
    ap.add_argument('--n', type=int, default=300)
    args = ap.parse_args()

    vocab = json.load(open(os.path.join(args.data, 'vocab.json'), encoding='utf-8'))
    itos, readings = vocab['itos'], vocab['readings']
    dev = np.load(os.path.join(args.data, 'dev.npz'))
    ck = torch.load(args.ckpt, map_location='cpu')
    model = NodeHomophoneScorer(**{k: v for k, v in ck['cfg'].items()})
    model.load_state_dict(ck['model'])
    model.eval()
    cand_ids_tbl, cand_mask_tbl = build_cand_table(vocab, torch.device('cpu'))

    # 排除左右文含 <unk> 的樣本：probe 走的是「文字 → id」，itos[1] 是
    # '<unk>' 這個多字元字串，切 UTF-8 會變成 '<','u',… —— 那是比對工具的
    # 限制，不是模型的，混進來只會製造假的不一致。
    ok = ~((dev['left'] == 1).any(axis=1) | (dev['right'] == 1).any(axis=1))
    pool = np.where(ok)[0]
    rng = np.random.default_rng(7)
    sel = rng.choice(pool, size=min(args.n, len(pool)), replace=False)

    lines, expect = [], []
    for i in sel:
        left = ''.join(itos[c] for c in dev['left'][i] if c != 0)
        right = ''.join(itos[c] for c in dev['right'][i] if c != 0)
        rid = int(dev['reading'][i])
        cands = [itos[c] for c in vocab['cand'][str(rid)]]
        lines.append(f'{left}\t{right}\t{readings[rid]}\t{",".join(cands)}')
        expect.append((i, rid, cands))

    out = subprocess.run([args.probe, args.model], input='\n'.join(lines),
                         capture_output=True, text=True)
    if out.returncode != 0:
        sys.exit(f'probe 失敗：{out.stderr}')
    cpp_rows = out.stdout.rstrip('\n').split('\n')
    if len(cpp_rows) != len(lines):
        sys.exit(f'probe 回了 {len(cpp_rows)} 行，送進去 {len(lines)} 行')

    worst, worst_at = 0.0, None
    bad_argmax = 0
    with torch.no_grad():
        for k, (i, rid, cands) in enumerate(expect):
            left = torch.from_numpy(dev['left'][i].astype(np.int64))[None]
            right = torch.from_numpy(dev['right'][i].astype(np.int64))[None]
            rd = torch.tensor([rid])
            cid, cmask = cand_ids_tbl[rd], cand_mask_tbl[rd]
            logits = model(left, right, rd, cid, cmask)
            lsm = torch.log_softmax(logits[0][cmask[0]], dim=-1).numpy()
            got = dict(p.split(':') for p in cpp_rows[k].split(',') if p)
            if len(got) != len(cands):
                sys.exit(f'第 {k} 行候選數對不上：C++ {len(got)} vs py {len(cands)}')
            cpp = np.array([float(got[c]) for c in cands])
            d = float(np.abs(cpp - lsm).max())
            if d > worst:
                worst, worst_at = d, k
            if int(cpp.argmax()) != int(lsm.argmax()):
                bad_argmax += 1

    print(f'比對 {len(expect)} 題：最大分差 {worst:.6f}（第 {worst_at} 題）'
          f'，argmax 不一致 {bad_argmax} 題')
    if worst > TOL or bad_argmax:
        print(f'❌ 沒過（容許 {TOL}）—— 匯出或 C++ 前向有錯，'
              f'後面所有 A/B 數字都不必看。')
        sys.exit(1)
    print('✅ C++ 與 PyTorch 同分。')


if __name__ == '__main__':
    main()
