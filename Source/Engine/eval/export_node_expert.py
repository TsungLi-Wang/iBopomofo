#!/usr/bin/env python3
# 把 train_node_expert.py 的 checkpoint 匯出成 C++ 讀得懂的 IZNEXP1。
#
# 新 magic、新 loader。**不沿用 LWLSTM**：那是路徑層的單向堆疊 LSTM，
# 這顆是節點層的封閉集合打分器，換副檔名接不上。
#
# 版面（小端；全部 float32，row-major，與 PyTorch Linear 的 [out, in] 一致）：
#
#   magic[8]   "IZNEXP1\0"
#   int32 ×5   emb syl_emb hid n_char n_syl
#   int32 ×3   ctx_chars cand_chars max_cands   （C++ 要跟訓練端逐位相同）
#   n_char × (int16 len + utf8)     字表
#   n_syl  × (int16 len + utf8)     音節表
#   char_emb [n_char, emb]
#   syl_emb  [n_syl, syl_emb]
#   ctx.0    [hid, emb*ctx_chars*2 + syl_emb + 1] + bias[hid]
#   ctx.2    [hid, hid] + bias[hid]
#   cand.0   [hid, emb*cand_chars + 4] + bias[hid]
#   cand.2   [hid, hid] + bias[hid]
#   head.0   [hid, 2*hid] + bias[hid]
#   head.2   [1, hid] + bias[1]

import argparse
import hashlib
import os
import struct
import sys

import numpy as np
import torch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from train_node_expert import CAND_CHARS, CTX_CHARS, MAX_CANDS  # noqa: E402

MAGIC = b'IZNEXP1\0'


def w(fh, arr):
    fh.write(np.ascontiguousarray(arr.detach().numpy(), dtype='<f4').tobytes())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--ckpt', required=True)
    ap.add_argument('--out', required=True)
    args = ap.parse_args()

    ck = torch.load(args.ckpt, map_location='cpu')
    sd, cfg = ck['model'], ck['cfg']
    itos, stos = ck['itos'], ck['stos']
    assert len(itos) == cfg['n_char'] and len(stos) == cfg['n_syl']

    with open(args.out, 'wb') as fh:
        fh.write(MAGIC)
        fh.write(struct.pack('<5i', cfg['emb'], cfg['syl_emb'], cfg['hid'],
                             cfg['n_char'], cfg['n_syl']))
        fh.write(struct.pack('<3i', CTX_CHARS, CAND_CHARS, MAX_CANDS))
        for s in itos + stos:
            b = s.encode('utf-8')
            fh.write(struct.pack('<h', len(b)))
            fh.write(b)
        w(fh, sd['char_emb.weight'])
        w(fh, sd['syl_emb.weight'])
        for name in ('ctx.0', 'ctx.2', 'cand.0', 'cand.2', 'head.0', 'head.2'):
            w(fh, sd[f'{name}.weight'])
            w(fh, sd[f'{name}.bias'])

    size = os.path.getsize(args.out)
    sha = hashlib.sha256(open(args.out, 'rb').read()).hexdigest()
    print(f'{args.out}  {size:,} bytes ({size / 1e6:.2f}MB)\nsha256 {sha}')


if __name__ == '__main__':
    main()
