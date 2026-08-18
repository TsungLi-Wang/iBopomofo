#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""棒⑮ 工作流 B：量「用現有 component 重新打分」這一**整個家族**的天花板。

**純分析。不訓練、不改 production、不 merge、不 enable、不跑正式 test。**

## 為什麼不是再做一個 reranker

⑭-R 掃了 (α, ν) 兩維權重 → cross-fitted **+69** 字。
⑭-S 訓了一個 MLP（同樣吃這些分數的衍生量）→ cross-fitted **+53** 字，NO-GO。

再做第三個成員只會再得到一個點。本棒改為量**整個家族的上界**：

    score = a·unigram + b·pmi + c·rnn

在**固定的 production top-10 候選集**上，全域掃 (a, b, c)，
取 net 最大者。這是所有「線性重新加權現有 component」方法的**共同上界** ——
⑭-R 是它的 2 維切片，⑭-S 是它的非線性推廣（但吃同一組資訊）。

若這個上界本身就不明顯高於 +69，**整個家族就可以收掉**，不必再做任何 prototype。

出貨對應的點是 (a, b, c) = (1, 1, 0.75)
（`walkScore = unigram + λ·PMI`，λ 已在 PMI 內；`fused = walkScore + ν·rnn`）。

## 紀律

* 候選集固定為 production 已產生的 top-10，不重新搜尋。
* naive（同一份語料掃出最大）與 cross-fitted 分開報，naive 不得當結論。
* 同時報 rescue / damage / net / precision，不得只報 net。
* document(＝句)-cluster bootstrap 給 CI。

用法：
  python3 audit_rescoring_family_ceiling.py --paths <paths-all.tsv> --out <片段.md>
"""

import argparse
import collections
import hashlib
import json

import numpy as np

SALT = 'baton14f-fold-v1'
K = 5
D2 = 3192
TOTAL_CHARS = 74649
PROD = (1.0, 1.0, 0.75)
BASE_R = 69      # ⑭-R cross-fitted counterfactual
BASE_S = 53      # ⑭-S learned reranker cross-fitted


def fold_of(doc):
    return int(hashlib.sha256(f'{SALT}:{doc}'.encode()).hexdigest()[:8], 16) % K


def load(path):
    s = collections.defaultdict(list)
    with open(path, encoding='utf-8') as fh:
        head = next(fh).rstrip('\n').split('\t')
        for line in fh:
            f = dict(zip(head, line.rstrip('\n').split('\t')))
            s[f['sid']].append((int(f['path_idx']), int(f['n_err']),
                                f['is_walk'] == '1',
                                float(f['unigram_sum']), float(f['pmi']),
                                float(f['rnn'])))
    out = {}
    for sid, ps in s.items():
        ps.sort()
        out[sid] = {
            'err': np.array([p[1] for p in ps], dtype=np.int32),
            'U': np.array([p[3] for p in ps]),
            'P': np.array([p[4] for p in ps]),
            'R': np.array([p[5] for p in ps]),
            'cur': next(p[1] for p in ps if p[2]),
            'fold': fold_of(sid),
        }
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--paths', required=True)
    ap.add_argument('--out', required=True)
    args = ap.parse_args()
    S = load(args.paths)
    sids = list(S)

    # 掃描網格（尺度不變，先固定 a=1；另外單獨試 a=0）
    grid = [(1.0, round(b, 3), round(c, 3))
            for b in np.arange(0.0, 3.001, 0.05)
            for c in np.arange(0.0, 4.001, 0.05)]
    grid += [(0.0, 1.0, round(c, 3)) for c in np.arange(0.0, 4.001, 0.05)]

    # 補齊成矩陣後向量化（各句候選數可能 <10，補 -inf 使其不會被選中）
    W = max(len(S[s]['err']) for s in sids)
    U = np.full((len(sids), W), -np.inf)
    P = np.zeros((len(sids), W))
    Rm = np.zeros((len(sids), W))
    E = np.zeros((len(sids), W), dtype=np.int32)
    for si, s in enumerate(sids):
        d = S[s]
        m = len(d['err'])
        U[si, :m] = d['U']
        P[si, :m] = d['P']
        Rm[si, :m] = d['R']
        E[si, :m] = d['err']
        E[si, m:] = d['err'][0]
    cur = np.array([S[s]['cur'] for s in sids], dtype=np.int32)
    newerr = np.zeros((len(grid), len(sids)), dtype=np.int32)
    rows = np.arange(len(sids))
    for gi, (a, b, c) in enumerate(grid):
        v = a * U + b * P + c * Rm
        newerr[gi] = E[rows, np.argmax(v, axis=1)]
    delta = cur[None, :] - newerr          # >0 = 救、<0 = 壞

    L, w = [], None
    L = []
    w = L.append
    w('## 家族定義與 sanity check\n')
    w('`score = a·unigram + b·pmi + c·rnn`，候選集固定為 production 的 top-10。')
    w(f'出貨點 = (a,b,c) = {PROD}。網格 {len(grid):,} 個權重組合。\n')
    pi = grid.index(PROD)
    w(f'\n**sanity check**：出貨點的 net = **{int(delta[pi].sum()):+d}** 字'
      f'（必須為 0，否則重算與出貨不一致）。\n')

    def tally(row):
        r = int(np.clip(row, 0, None).sum())
        d = int(np.clip(-row, 0, None).sum())
        return r, d, r - d

    # ── naive 全域最佳 ──
    nets = delta.sum(axis=1)
    bi = int(np.argmax(nets))
    r, d, n = tally(delta[bi])
    w('\n\n## NAIVE 全域最佳（同一份語料掃出，**不得當結論**）\n')
    w('| | (a, b, c) | rescue | damage | net | precision | 字級正確率 |')
    w('|---|---|---|---|---|---|---|')
    w(f'| 出貨 | {PROD} | 0 | 0 | +0 | — | '
      f'{100*(1-cur.sum()/TOTAL_CHARS):.3f}% |')
    w(f'| **NAIVE 最佳** | {grid[bi]} | {r} | {d} | **{n:+d}** | '
      f'{r/(r+d):.3f} | {100*(1-newerr[bi].sum()/TOTAL_CHARS):.3f}% |')

    # ── cross-fitted ──
    folds = np.array([S[s]['fold'] for s in sids])
    R = D = 0
    picks = []
    for k in range(K):
        tr = folds != k
        te = folds == k
        bg = int(np.argmax(delta[:, tr].sum(axis=1)))
        picks.append(grid[bg])
        rr, dd, _ = tally(delta[bg, te])
        R += rr
        D += dd
    w('\n\n## CROSS-FITTED（document/句級 5-fold，4 選 1 評）\n')
    w('| | rescue | damage | net | precision | 佔 D2 | 字級 |')
    w('|---|---|---|---|---|---|---|')
    w(f'| **本棒：家族天花板** | {R} | {D} | **{R-D:+d}** | '
      f'{R/(R+D):.3f} | {(R-D)/D2:+.1%} | +{100*(R-D)/TOTAL_CHARS:.3f}pp |')
    w(f'| ⑭-R（(α,ν) 2 維切片）| 177 | 108 | **+{BASE_R}** | 0.621 | '
      f'+{BASE_R/D2:.1%} | +{100*BASE_R/TOTAL_CHARS:.3f}pp |')
    w(f'| ⑭-S（learned MLP）| 239 | 186 | **+{BASE_S}** | 0.562 | '
      f'+{BASE_S/D2:.1%} | +{100*BASE_S/TOTAL_CHARS:.3f}pp |')
    w(f'\n逐 fold 選出的 (a,b,c)：' + '、'.join(str(p) for p in picks))

    # ── bootstrap ──
    rng = np.random.default_rng(0)
    per = np.zeros(len(sids))
    for k in range(K):
        tr = folds != k
        te = folds == k
        bg = int(np.argmax(delta[:, tr].sum(axis=1)))
        per[te] = delta[bg, te]
    boots = [per[rng.integers(0, len(sids), len(sids))].sum()
             for _ in range(2000)]
    boots.sort()
    w(f'\n**95% CI（document-cluster bootstrap，2,000 次）：'
      f'[{boots[50]:+.0f}, {boots[1949]:+.0f}]**')

    # ── 上界：逐句 oracle（每句各自挑最好的權重）──
    best_per_sent = delta.max(axis=0)
    w('\n\n## 逐句 oracle（每一句各自挑最有利的權重，`THEORETICAL UPPER BOUND`）\n')
    w(f'net = **{int(np.clip(best_per_sent,0,None).sum())}** 字'
      f'（＝{int(np.clip(best_per_sent,0,None).sum())/D2:.1%} of D2）。')
    w('**這個數字不可達** —— 它允許每一句用不同的權重，'
      '而 production 只有一組全域權重。列出來只是為了界定家族的絕對上界。')

    # ── 曲線 ──
    w('\n\n## net 對 c（rnn 權重）的形狀，b 固定在出貨值 1.0\n')
    w('| c | rescue | damage | net |')
    w('|---|---|---|---|')
    for c in (0.0, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0):
        gi = grid.index((1.0, 1.0, round(c, 3)))
        r2, d2, n2 = tally(delta[gi])
        mark = ' ←出貨' if abs(c - 0.75) < 1e-9 else ''
        w(f'| {c:.2f}{mark} | {r2} | {d2} | **{n2:+d}** |')

    with open(args.out, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(L) + '\n')
    print('\n'.join(L))
    print(f'\n@@xfit_net={R-D} naive={n} lo={boots[50]:.0f} hi={boots[1949]:.0f}')


if __name__ == '__main__':
    main()
