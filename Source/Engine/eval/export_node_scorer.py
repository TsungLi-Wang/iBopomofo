#!/usr/bin/env python3
# 把 train_node_homophone.py 的 checkpoint 匯出成 C++ 端讀得懂的 IZNODE1。
#
# 為什麼是新 magic 不是沿用 LWLSTM（docs/decisions/0008 第四節）：
# LWLSTM 的 loader 有 layers_ > 4 的硬上限，而且它讀的是「單向堆疊 LSTM +
# 全詞表 softmax」。這顆是雙向 + 注音條件 + 候選受限，**換副檔名接不上**。
#
# 版面（小端，全部 float32 row-major，與 PyTorch 的 [out, in] 一致）：
#
#   magic[8]        "IZNODE1\0"
#   int32 ×7        emb hidden layers read_emb merge n_char n_reading
#   n_char  × (int16 len + utf8 bytes)          字表
#   n_reading × (int16 len + utf8 bytes)        讀音表
#   n_reading × (int16 count + count×int32)     讀音 → 候選字 id
#   char_emb   [n_char, emb]
#   read_emb   [n_reading, read_emb]
#   lstm_l ×layers: w_ih[4H,in] w_hh[4H,H] b_ih[4H] b_hh[4H]    (in = emb / H)
#   lstm_r ×layers: 同上
#   merge0_w [merge, 2H+read_emb]  merge0_b [merge]
#   merge1_w [merge, merge]        merge1_b [merge]
#   out_w    [n_char, merge]       out_b    [n_char]
#
# LSTM 閘序 i,f,g,o —— 與 PyTorch 及 NeuralLMPathScorer.cpp 的 lstmStep 一致。

import argparse
import hashlib
import json
import os
import struct

import numpy as np
import torch

MAGIC = b'IZNODE1\0'


def w(fh, arr):
    fh.write(np.ascontiguousarray(arr, dtype='<f4').tobytes())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--ckpt', required=True)
    ap.add_argument('--data', required=True, help='vocab.json 所在目錄')
    ap.add_argument('--out', required=True)
    args = ap.parse_args()

    ck = torch.load(args.ckpt, map_location='cpu')
    sd, cfg = ck['model'], ck['cfg']
    vocab = json.load(open(os.path.join(args.data, 'vocab.json'), encoding='utf-8'))
    itos, readings, cand = vocab['itos'], vocab['readings'], vocab['cand']
    assert len(itos) == cfg['n_char'] and len(readings) == cfg['n_reading']

    with open(args.out, 'wb') as fh:
        fh.write(MAGIC)
        fh.write(struct.pack('<7i', cfg['emb'], cfg['hidden'], cfg['layers'],
                             cfg['read_emb'], cfg['merge'], cfg['n_char'],
                             cfg['n_reading']))
        for s in itos + readings:
            b = s.encode('utf-8')
            fh.write(struct.pack('<h', len(b)))
            fh.write(b)
        for i in range(len(readings)):
            ids = cand.get(str(i), [])
            fh.write(struct.pack('<h', len(ids)))
            fh.write(np.asarray(ids, dtype='<i4').tobytes())

        w(fh, sd['char_emb.weight'])
        w(fh, sd['read_emb.weight'])
        for tag in ('lstm_l', 'lstm_r'):
            for li in range(cfg['layers']):
                for name in ('weight_ih_l', 'weight_hh_l', 'bias_ih_l', 'bias_hh_l'):
                    w(fh, sd[f'{tag}.{name}{li}'])
        w(fh, sd['merge.0.weight'])
        w(fh, sd['merge.0.bias'])
        w(fh, sd['merge.3.weight'])
        w(fh, sd['merge.3.bias'])
        w(fh, sd['out.weight'])
        w(fh, sd['out.bias'])

    size = os.path.getsize(args.out)
    sha = hashlib.sha256(open(args.out, 'rb').read()).hexdigest()
    print(f'{args.out}  {size:,} bytes ({size / 1e6:.1f}MB)\nsha256 {sha}')


if __name__ == '__main__':
    main()
