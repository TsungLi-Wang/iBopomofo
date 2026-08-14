#!/usr/bin/env python3
# C++（NodeHomophoneExpert）與 PyTorch（train_node_expert）逐題同分檢查。
# 由 scripts/node-expert-parity.sh 呼叫；為什麼要有這道關卡寫在那支裡。
#
# 直接吃 node_sample_extract 產生的 nodes.tsv，所以驗到的是**整條特徵管線**
# （候選排序與截斷、左右文補 PAD 的對齊、引擎分數縮放、音節加總、GELU），
# 不只是矩陣乘法。

import argparse
import os
import subprocess
import sys

import numpy as np
import torch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from train_node_expert import NodeExpert, encode, load_rows  # noqa: E402

TOL = 2e-3


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--probe', required=True)
    ap.add_argument('--model', required=True)
    ap.add_argument('--nodes', required=True)
    ap.add_argument('--ckpt', required=True)
    ap.add_argument('--n', type=int, default=400)
    args = ap.parse_args()

    ck = torch.load(args.ckpt, map_location='cpu')
    itos, stos = ck['itos'], ck['stos']
    model = NodeExpert(**ck['cfg'])
    model.load_state_dict(ck['model'])
    model.eval()

    # 只取前 n 行，probe 與 python 讀同一批、同一順序。
    head = os.path.join(os.path.dirname(args.model), '_parity_head.tsv')
    with open(args.nodes, encoding='utf-8') as src, \
            open(head, 'w', encoding='utf-8') as dst:
        for i, line in enumerate(src):
            if i > args.n:
                break
            dst.write(line)

    out = subprocess.run([args.probe, args.model],
                         stdin=open(head, encoding='utf-8'),
                         capture_output=True, text=True)
    if out.returncode != 0:
        sys.exit(f'probe 失敗：{out.stderr}')
    cpp_rows = out.stdout.split('\n')

    # Python 端：用訓練時同一套 loader／encoder，但要知道哪些行被丟掉了，
    # 才能跟 probe 的逐行輸出對齊 —— 所以這裡自己走一遍，不用 load_rows 的
    # 過濾（probe 不做 ㄉㄜ˙／lattice-miss 過濾，它對每一行都打分）。
    rows = []
    keep_idx = []
    with open(head, encoding='utf-8') as fh:
        next(fh)
        for i, line in enumerate(fh):
            f = line.rstrip('\n').split('\t')
            if len(f) < 16:
                continue
            cands = []
            for c in f[15].split('|'):
                p = c.split(':')
                if len(p) == 5:
                    cands.append((p[0], float(p[1]), float(p[2]), float(p[3]),
                                  p[4] == '1'))
            if len(cands) < 2:
                continue
            cands.sort(key=lambda x: -x[1])
            cands = cands[:24]
            rows.append({'reading': f[6], 'gold': f[8], 'chosen': f[7],
                         'gi': 0, 'cands': cands, 'left': f[12],
                         'right': f[13], 'right_empty': f[14] == '1',
                         'split': f[1], 'kind': int(f[2]), 'hard': False})
            keep_idx.append(i)

    ci = {c: i for i, c in enumerate(itos)}
    si = {s: i for i, s in enumerate(stos)}
    enc = encode(rows, ci, si)

    worst, worst_at, bad_argmax, compared = 0.0, None, 0, 0
    with torch.no_grad():
        logits = model(
            torch.from_numpy(enc['left'].astype(np.int64)),
            torch.from_numpy(enc['right'].astype(np.int64)),
            torch.from_numpy(enc['syl'].astype(np.int64)),
            torch.from_numpy(enc['rempty']),
            torch.from_numpy(enc['cchars'].astype(np.int64)),
            torch.from_numpy(enc['cfeat']),
            torch.from_numpy(enc['cmask']))
    for k, i in enumerate(keep_idx):
        if i >= len(cpp_rows) or not cpp_rows[i].strip():
            continue
        cpp = np.array([float(v) for v in cpp_rows[i].split(',')])
        m = enc['cmask'][k]
        lsm = torch.log_softmax(logits[k][torch.from_numpy(m)], dim=-1).numpy()
        if len(cpp) != len(lsm):
            sys.exit(f'第 {i} 行候選數對不上：C++ {len(cpp)} vs py {len(lsm)}')
        d = float(np.abs(cpp - lsm).max())
        compared += 1
        if d > worst:
            worst, worst_at = d, i
        if int(cpp.argmax()) != int(lsm.argmax()):
            bad_argmax += 1

    os.remove(head)
    print(f'比對 {compared} 個節點：最大分差 {worst:.6f}（第 {worst_at} 行）'
          f'，argmax 不一致 {bad_argmax} 個')
    if compared == 0:
        sys.exit('❌ 一個都沒比到 —— 對齊邏輯壞了')
    if worst > TOL or bad_argmax:
        print(f'❌ 沒過（容許 {TOL}）—— 匯出或 C++ 前向有錯，'
              f'後面所有 A/B 數字都不必看。')
        sys.exit(1)
    print('✅ C++ 與 PyTorch 同分。')


if __name__ == '__main__':
    main()
