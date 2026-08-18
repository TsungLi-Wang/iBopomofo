#!/usr/bin/env python3
# 局部搭配表徵實驗的 diagnostic（棒⑭-I 第一階段）。
#
# ⚠️ 這一支仍然是 **representation diagnostic，不是 model training result**。
# 它比較的是「同一個固定容量的線性分類器，餵不同的表徵」——
# 不產生任何可上線的權重，不碰 τ、架構、production。
#
# ## 為什麼是 bigram
#
# 棒⑭-H 量到：判別力來自**局部詞彙搭配**（手作／大作／神作／合作），
# 而現在的 NodeExpert 只有「字元 embedding 串接 → 淺層 MLP」，
# bag-of-chars 都能贏它（0.728 vs 0.587）。
# 但 bag-of-chars **本身也表達不了搭配**——它看得到「手」，
# 看不到「手＋作」這個組合。所以下一個最小的表徵改動就是把相鄰字對放進來。
#
#   B0 = bag-of-chars（＝棒⑭-H 的 walk ±6，重現用）
#   I1 = B0 + 視窗內相鄰字對（含與目標字相接的那兩個）
#   I2 = I1 + **候選條件化**的字對：把每個候選字代入目標位置後的
#        (左1,候選) 與 (候選,右1)——推論時候選是已知的，沒有洩漏
#
# 視窗一律固定 ±6，全部只用 walk 輸出的字。

import argparse
import collections
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from audit_representation import (boot_ci, fit_lr, load,  # noqa: E402
                                  pr_auc, roc_auc)

K = 6
TARGET = '作'
OTHERS = ['做', '座', '坐']


def ctx(r):
    """walk 輸出的左右字（推論時可得）。左邊取尾 K、右邊取頭 K。"""
    return r['left'][-K:], r['right'][:K]


def build_vocabs(rows, min_count=3):
    uni, bi, cbi = collections.Counter(), collections.Counter(), collections.Counter()
    for r in rows:
        l, rt = ctx(r)
        seq = list(l) + [TARGET] + list(rt)
        for ch in l:
            uni[('L', ch)] += 1
        for ch in rt:
            uni[('R', ch)] += 1
        for i in range(len(seq) - 1):
            bi[(seq[i], seq[i + 1])] += 1
        names = [c[0] for c in r['cands']]
        for cand in OTHERS:
            if cand not in names:
                continue
            if l:
                cbi[('L', l[-1], cand)] += 1
            if rt:
                cbi[('R', cand, rt[0])] += 1
    keep = lambda c: {k: i for i, (k, n) in enumerate(
        x for x in c.most_common() if x[1] >= min_count)}
    return keep(uni), keep(bi), keep(cbi)


def feat_B0(r, V):
    uni, _, _ = V
    v = np.zeros(len(uni), dtype=np.float32)
    l, rt = ctx(r)
    for ch in l:
        k = ('L', ch)
        if k in uni:
            v[uni[k]] += 1
    for ch in rt:
        k = ('R', ch)
        if k in uni:
            v[uni[k]] += 1
    return v


def feat_I1(r, V):
    uni, bi, _ = V
    v = np.zeros(len(bi), dtype=np.float32)
    l, rt = ctx(r)
    seq = list(l) + [TARGET] + list(rt)
    for i in range(len(seq) - 1):
        k = (seq[i], seq[i + 1])
        if k in bi:
            v[bi[k]] += 1
    return np.concatenate([feat_B0(r, V), v])


def feat_I2(r, V):
    uni, bi, cbi = V
    v = np.zeros(len(cbi), dtype=np.float32)
    l, rt = ctx(r)
    names = [c[0] for c in r['cands']]
    for cand in OTHERS:
        if cand not in names:
            continue
        if l:
            k = ('L', l[-1], cand)
            if k in cbi:
                v[cbi[k]] += 1
        if rt:
            k = ('R', cand, rt[0])
            if k in cbi:
                v[cbi[k]] += 1
    return np.concatenate([feat_I1(r, V), v])


def oof(rows, fn, l2):
    X = np.stack([fn(r) for r in rows])
    mu, sd = X.mean(0), X.std(0) + 1e-6
    y = np.array([r['label'] for r in rows], dtype=np.float32)
    s = np.zeros(len(rows))
    per_fold = {}
    for fi in range(5):
        te = np.array([i for i, r in enumerate(rows) if r['fold'] == fi])
        tr = np.array([i for i, r in enumerate(rows) if r['fold'] != fi])
        if not len(te) or not len(tr):
            continue
        # ── 每個 fold 都 assert 文件不重疊 ──
        assert not (set(rows[i]['doc'] for i in tr)
                    & set(rows[i]['doc'] for i in te)), f'fold {fi} 文件重疊'
        w, b = fit_lr((X[tr] - mu) / sd, y[tr], l2=l2)
        s[te] = ((X[te] - mu) / sd) @ w + b
        per_fold[fi] = roc_auc(list(s[te]), list(y[te]))
    return s, y, per_fold, X.shape[1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--nodes', required=True)
    ap.add_argument('--sentences', required=True)
    ap.add_argument('--nodes2', default='')
    ap.add_argument('--sentences2', default='')
    ap.add_argument('--folds', required=True)
    ap.add_argument('--l2', type=float, default=2.0)
    ap.add_argument('--out', required=True)
    args = ap.parse_args()

    fj = json.load(open(args.folds, encoding='utf-8'))
    rows = load(args.nodes, args.sentences, 'train-src', fj['assign'])
    if args.nodes2:
        rows += load(args.nodes2, args.sentences2, 'contexts', fj['assign'])
    seen, ded = set(), []
    for r in rows:
        k = (r['doc'], r['text'], r['pos'])
        if k in seen:
            continue
        seen.add(k)
        ded.append(r)
    rows = ded
    V = build_vocabs(rows)
    docs = [r['doc'] for r in rows]

    out = []
    w = out.append
    w('# 局部搭配表徵 diagnostic（棒⑭-I 第一階段）\n')
    w('> **representation diagnostic，不是 model training result。**')
    w('> 同一個固定容量的 L2 logistic regression，只換餵進去的表徵；')
    w('> τ、架構、production 全未動，不產生任何可上線的權重。\n')
    n1 = sum(r['label'] for r in rows)
    w(f'\n診斷集 **{len(rows)}**（該出手 {n1}、不該出手 {len(rows) - n1}）、'
      f'{len(set(docs))} 份文件；視窗固定 ±{K}，**全部用 walk 輸出的字**。\n')
    w(f'\n字表（出現 ≥3 次）：unigram {len(V[0])}、bigram {len(V[1])}、'
      f'候選條件化 bigram {len(V[2])}。L2 = {args.l2}（三者相同）。\n')

    w('\n## 結果（out-of-fold，document-level 5-fold）\n')
    w('| 表徵 | 維度 | ROC-AUC | 95% CI | PR-AUC | 逐 fold AUC |')
    w('|---|---|---|---|---|---|')
    store = {}
    for name, fn in (('B0 bag-of-chars（＝⑭-H baseline）', feat_B0),
                     ('**I1 ＋相鄰字對**', feat_I1),
                     ('**I2 ＋候選條件化字對**', feat_I2)):
        s, y, pf, dim = oof(rows, lambda r, fn=fn: fn(r, V), args.l2)
        a = roc_auc(list(s), list(y))
        lo, hi = boot_ci(list(s), list(y), docs)
        store[name] = (s, y)
        w(f'| {name} | {dim} | **{a:.3f}** | [{lo:.3f}, {hi:.3f}] | '
          f'{pr_auc(s, y):.3f} | '
          + ' '.join(f'{pf[k]:.2f}' for k in sorted(pf)) + ' |')

    w('\n## 逐 pairwise\n')
    w('| 表徵 | **vs 作→做** | vs 作→座 | vs 作→坐 |')
    w('|---|---|---|---|')
    for name in store:
        s, y = store[name]
        cells = []
        for g in OTHERS:
            idx = [i for i, r in enumerate(rows) if r['gold'] in (TARGET, g)]
            sc = [s[i] for i in idx]
            lb = [1 if rows[i]['gold'] == g else 0 for i in idx]
            dd = [rows[i]['doc'] for i in idx]
            a = roc_auc(sc, lb)
            lo, hi = boot_ci(sc, lb, dd, n=400)
            cells.append(f'**{a:.3f}** [{lo:.2f}, {hi:.2f}]' if g == '做'
                         else f'{a:.3f} [{lo:.2f}, {hi:.2f}]')
        w(f'| {name} | ' + ' | '.join(cells) + ' |')

    with open(args.out, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(out) + '\n')
    print('\n'.join(out))


if __name__ == '__main__':
    main()
